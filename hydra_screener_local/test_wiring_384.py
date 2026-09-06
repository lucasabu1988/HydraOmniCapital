"""TASK-384 — post-freeze wiring: runlog around the v9 step, migrate on load, preflight
replay HARD + universe-source WARN, PIT snapshot hook, manifest_path in the journal."""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import daily as daily_mod  # noqa: E402
import portfolio_v9 as V  # noqa: E402
import preflight as PF  # noqa: E402
from config import V9  # noqa: E402
from core import portfolio_engine as E  # noqa: E402
from core.journal import build_record  # noqa: E402
from test_portfolio_v9_cli import FakeEngine, _market, _rank  # noqa: E402
from utils.runlog import start_run  # noqa: E402


def _statuses(result):
    return {r["check"]: r["status"] for r in result["rows"]}


# ----------------------------------------------------------------- load_state + migrate
def test_load_state_fills_missing_keys(tmp_path):
    st = E.new_state(1000.0, "2026-09-04", V9)
    st.pop("interest")
    for tr in st["sleeves"]["stocks"]["tranches"]:
        tr.pop("stale")
    p = tmp_path / "portfolio_v9.json"
    p.write_text(json.dumps(st), encoding="utf-8")
    loaded = V.load_state(p)
    assert loaded["interest"] == [] and loaded["dividends"] == []
    assert all("stale" in tr for tr in loaded["sleeves"]["stocks"]["tranches"])
    assert loaded["schema_version"] == 1


def test_load_state_refuses_unknown_schema(tmp_path):
    st = E.new_state(1000.0, "2026-09-04", V9)
    st["schema_version"] = 7
    p = tmp_path / "portfolio_v9.json"
    p.write_text(json.dumps(st), encoding="utf-8")
    with pytest.raises(SystemExit) as ex:
        V.load_state(p)
    assert "unknown schema" in str(ex.value)


# ----------------------------------------------------------------- preflight: state replay
def _frames():
    dates = pd.DatetimeIndex(["2026-09-03", "2026-09-04"])
    prices = pd.DataFrame({f"T{i}": [10.0, 10.5] for i in range(10)}, index=dates)
    etf = pd.DataFrame({t: [100.0, 101.0] for t in V9["etf_universe"]}, index=dates)
    irx = pd.Series([5.0, 5.1], index=dates)
    return prices, etf, irx


def test_preflight_replay_ok_on_fresh_state_with_pending():
    """Execution-day configuration: pending orders present, ledger empty, last_run_date = plan date."""
    prices, etf, irx = _frames()
    st = E.new_state(100000.0, "2026-09-04", V9)
    st["last_run_date"] = "2026-09-04"
    st["pending"] = [{"planned": "2026-09-04", "sleeve": "stocks", "tranche": 0, "ticker": "T0",
                      "side": "buy", "dollars": 1000.0}]
    r = PF.evaluate(prices, etf, irx, state=st, last_session="2026-09-04", backup_dir="x")
    assert _statuses(r)["state replay"] == "OK"
    assert not r["hard"]


def test_preflight_replay_mismatch_is_hard():
    prices, etf, irx = _frames()
    st = E.new_state(100000.0, "2026-09-04", V9)
    st["sleeves"]["stocks"]["tranches"][0]["cash"] += 123.45      # cash that no record explains
    r = PF.evaluate(prices, etf, irx, state=st, last_session="2026-09-04", backup_dir="x")
    assert _statuses(r)["state replay"] == "HARD"
    assert r["hard"]
    with pytest.raises(SystemExit):
        PF.raise_if_hard(r)


def test_preflight_replay_skips_without_state():
    prices, etf, irx = _frames()
    r = PF.evaluate(prices, etf, irx, state=None, last_session="2026-09-04", backup_dir="x")
    assert _statuses(r)["state replay"] == "SKIP"


# ----------------------------------------------------------------- preflight: universe source
def test_preflight_universe_fallback_warns():
    prices, etf, irx = _frames()
    rep = {"universe": "sp500", "source_used": "fallback", "count": 503, "from_cache": False, "fallback": True}
    r = PF.evaluate(prices, etf, irx, state=None, last_session="2026-09-04", backup_dir="x", universe_report=rep)
    assert _statuses(r)["universe source"] == "WARN"
    assert r["warn"] and not r["hard"]


def test_preflight_universe_ok_and_skip():
    prices, etf, irx = _frames()
    rep = {"universe": "all", "source_used": "union", "count": 3002, "from_cache": False, "fallback": False}
    r = PF.evaluate(prices, etf, irx, state=None, last_session="2026-09-04", backup_dir="x", universe_report=rep)
    assert _statuses(r)["universe source"] == "OK"
    r2 = PF.evaluate(prices, etf, irx, state=None, last_session="2026-09-04", backup_dir="x")
    assert _statuses(r2)["universe source"] == "SKIP"


# ----------------------------------------------------------------- runlog around run()
def test_run_with_runlog_records_fingerprints_and_artifacts(tmp_path):
    ctx = start_run("test_v9", argv=["x"], runs_dir=tmp_path / "runs", git_info=("abc", False))
    with ctx:
        out = V.run(tmp_path / "state", capital=100000.0, fetch_fn=_market, rank_fn=_rank,
                    engine=FakeEngine(), silent=True, runlog=ctx)
    m = json.loads((ctx.directory / "manifest.json").read_text(encoding="utf-8"))
    assert set(m["fingerprints"]) == {"stocks", "etf", "^IRX"}
    assert m["fingerprints"]["stocks"]["last_bar"] == out["today"]
    arts = [Path(a).name for a in m["artifacts"]]
    assert "portfolio_v9.json" in arts and any(a.startswith("instructions_") and a.endswith(".md") for a in arts)
    assert out["manifest_path"] == str(ctx.directory / "manifest.json")
    assert m["exit_status"] == 0


def test_run_without_runlog_is_unchanged(tmp_path):
    out = V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=FakeEngine(), silent=True)
    assert out["manifest_path"] is None


def test_journal_record_carries_manifest_path():
    rec = build_record(date="2026-09-04", state={}, manifest_path="runs/x/manifest.json")
    assert rec["process"]["manifest_path"] == "runs/x/manifest.json"
    rec2 = build_record(date="2026-09-04", state={})
    assert rec2["process"]["manifest_path"] is None


# ----------------------------------------------------------------- daily hook: PIT snapshots + manifest
def _quiet_daily(monkeypatch):
    monkeypatch.setattr(daily_mod, "run_screener", lambda universe: 0)
    monkeypatch.setattr(daily_mod, "backup_history_after_run", lambda: None)
    monkeypatch.setattr(daily_mod, "print_tv_instructions", lambda: None)
    monkeypatch.setattr(daily_mod, "maybe_refresh_pnl", lambda x: None)


def test_daily_snapshots_only_after_a_real_run(monkeypatch, tmp_path):
    _quiet_daily(monkeypatch)
    import snapshot_universe as SU
    calls = []
    monkeypatch.setattr(SU, "snapshot_after_run", lambda universe, date=None, pit_dir=None: calls.append(universe) or [])
    monkeypatch.setattr("utils.runlog.DEFAULT_RUNS_DIR", tmp_path / "runs")

    monkeypatch.setattr("portfolio_v9.run", lambda *a, **k: {"orders": []})           # dry: no prices
    assert daily_mod.main(["--skip-screener", "--no-instructions", "--v9"]) == 0
    assert calls == []

    fake = {"orders": [], "prices": pd.DataFrame({"A": [1.0]}), "state": None}
    monkeypatch.setattr("portfolio_v9.run", lambda *a, **k: fake)
    assert daily_mod.main(["--skip-screener", "--no-instructions", "--v9", "--universe", "sp500"]) == 0
    assert calls == ["sp500"]


def test_daily_writes_a_run_manifest(monkeypatch, tmp_path):
    _quiet_daily(monkeypatch)
    monkeypatch.setattr("utils.runlog.DEFAULT_RUNS_DIR", tmp_path / "runs")
    seen = {}
    monkeypatch.setattr("portfolio_v9.run", lambda *a, **k: seen.update(k) or {"orders": []})
    rc = daily_mod.main(["--skip-screener", "--no-instructions", "--v9"])
    assert rc == 0
    assert seen.get("runlog") is not None                      # the context reaches portfolio_v9.run
    runs = list((tmp_path / "runs").glob("*_daily"))
    assert len(runs) == 1
    m = json.loads((runs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert m["exit_status"] == 0 and m["name"] == "daily"


# ----------------------------------------------------------------- off-disk mirror of pit/ and runs/
def test_offdisk_backup_mirrors_pit_and_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "bk"))
    pit = V.ROOT / "data_cache" / "pit"
    had_pit = pit.exists()
    st = tmp_path / "s.json"
    st.write_text("{}", encoding="utf-8")
    dest = V.copy_state_off_disk("2026-09-04", [st], silent=True)
    assert (dest / "s.json").exists()
    if had_pit:
        assert (tmp_path / "bk" / "pit").exists()


def test_journal_regime_label_reads_ranking_contract_column():
    """SPEC 7 names the column `regime_type`; the journal used to read `meta_regime_type` (always None)."""
    rk = pd.DataFrame({"ticker": ["A"], "rank": [1], "regime": [0.61], "regime_type": ["NEUTRAL"],
                       "recommended": [True], "recommended_count": [1], "sector": ["Other"]})
    rec = build_record(date="2026-09-08", state={}, ranking=rk)
    assert rec["seen"]["regime_label"] == "NEUTRAL"
    assert rec["seen"]["regime_score"] == 0.61
