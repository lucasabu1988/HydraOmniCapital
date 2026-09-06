"""TASK-340 — v9 CLI persistence and idempotence. No network: fetch and engine are fakes."""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import daily as daily_mod  # noqa: E402
import portfolio_v9 as V  # noqa: E402
from config import V9  # noqa: E402


IDX = pd.DatetimeIndex(["2026-09-04"])
ETF_UNIVERSE = list(V9["etf_universe"])


def _market(_universe=None):
    prices = pd.DataFrame({"AAA": [10.0]}, index=IDX)
    etf = pd.DataFrame({t: [100.0] for t in ETF_UNIVERSE}, index=IDX)
    spy = pd.Series([400.0], index=IDX, name="SPY")
    irx = pd.Series([5.25], index=IDX)          # percent; CLI must pass 0.0525 to plan()
    return dict(prices=prices, volumes=prices * 1000, spy=spy, etf=etf, irx=irx,
                stock_report={}, etf_report={}, irx_report={})


def _rank(prices, spy, volumes):
    return pd.DataFrame({"ticker": ["AAA"], "rank": [1], "sector": ["Other"],
                         "recommended": [True], "reason": [""], "recommended_count": [1]})


class FakeEngine:
    """Records calls; plan is idempotent on last_run_date like the real engine."""

    def __init__(self):
        self.plans = 0
        self.settles = 0
        self.tbill_seen = []

    def new_state(self, capital, anchor, cfg):
        import core.portfolio_engine as E
        return E.new_state(capital, anchor, cfg)

    def settle(self, state, exec_date, stock_row, etf_row, cfg):
        self.settles += 1
        fills = list(state.get("pending") or [])
        for f in fills:
            f.update(exec_date=exec_date, status="filled")
        state["ledger"] = state.get("ledger", []) + fills
        state["pending"] = []
        return fills

    def plan(self, state, today, ranking, stock_prices, etf_prices, tbill_rate, cfg):
        self.tbill_seen.append(tbill_rate)
        if state.get("last_run_date") == today:
            return state, []
        if state.get("pending"):
            raise RuntimeError("pending")
        self.plans += 1
        state["last_run_date"] = today
        orders = [{"sleeve": "stocks", "tranche": 0, "ticker": "AAA", "side": "buy",
                   "dollars": 100.0, "est_units": 10.0, "est_price": 10.0, "planned": today,
                   "week": 0, "cost_bp": 10.0}]
        state["pending"] = orders
        state["week_index"] = 0
        state["last_renewal_date"] = today
        return state, orders

    def summary_table(self, state, stock_row, etf_row, cfg):
        return {"total": 100000.0,
                "sleeves": {
                    "stocks": {"value": 50000.0, "share": 0.5, "cash": 50000.0,
                               "exposure": 0.0, "distinct": 0, "names": []},
                    "etf": {"value": 50000.0, "share": 0.5, "cash": 50000.0,
                            "exposure": 0.0, "distinct": 0, "names": []},
                }}


def test_first_run_writes_state_backup_and_instructions(tmp_path):
    eng = FakeEngine()
    out = V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=eng, silent=True)
    assert Path(out["state_path"]).exists()
    state = json.loads(Path(out["state_path"]).read_text(encoding="utf-8"))
    assert state["capital_reference"] == 100000.0
    assert state["schema_version"] == 1
    assert out["orders"] and out["orders"][0]["ticker"] == "AAA"
    md = Path(out["instructions_md"])
    js = md.with_suffix(".json")
    assert md.exists() and js.exists()
    assert "AAA" in md.read_text(encoding="utf-8")
    body = json.loads(js.read_text(encoding="utf-8"))
    assert body["date"] == "2026-09-04"
    assert "ejecutar al cierre del 2026-09-07" in body["execute"]
    assert "ejecutar al cierre del 2026-09-07" in md.read_text(encoding="utf-8")
    assert len(eng.tbill_seen) == 1 and isinstance(eng.tbill_seen[0], pd.Series)   # full history
    assert float(eng.tbill_seen[0].iloc[-1]) == pytest.approx(0.0525)              # percent / 100
    assert not (tmp_path / "backup").exists() or not list((tmp_path / "backup").glob("*.json"))


def test_second_run_same_date_does_not_duplicate_orders(tmp_path):
    eng = FakeEngine()
    V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=eng, silent=True)
    out = V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=eng, silent=True)
    assert eng.plans == 1
    assert eng.settles == 0                                   # still t, not t+1
    assert out["orders"] == []
    assert out["no_trades"] is True
    # the sheet for this date must still show the pending orders planned today (a rerun must not
    # overwrite the instructions with "No trades"; integration review 340)
    text = Path(out["instructions_md"]).read_text(encoding="utf-8")
    assert "No trades today" not in text
    assert "| sleeve | tranche | side |" in text
    backups = list((tmp_path / "backup").glob("*.json"))
    assert len(backups) == 1
    state = json.loads(Path(tmp_path / "portfolio_v9.json").read_text(encoding="utf-8"))
    assert len(state["pending"]) == 1


def test_next_bar_settles_then_can_plan_again(tmp_path):
    eng = FakeEngine()
    V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=eng, silent=True)

    def later(_u=None):
        idx = pd.DatetimeIndex(["2026-09-04", "2026-09-05"])
        return dict(
            prices=pd.DataFrame({"AAA": [10.0, 10.0]}, index=idx),
            volumes=pd.DataFrame({"AAA": [10_000.0, 10_000.0]}, index=idx),
            spy=pd.Series([400.0, 401.0], index=idx),
            etf=pd.DataFrame({t: [100.0, 101.0] for t in ETF_UNIVERSE}, index=idx),
            irx=pd.Series([5.25, 5.20], index=idx),
            stock_report={}, etf_report={}, irx_report={},
        )

    out = V.run(tmp_path, fetch_fn=later, rank_fn=_rank, engine=eng, silent=True)
    assert eng.settles == 1
    assert eng.plans == 2
    assert out["fills"] and out["orders"]


def test_first_run_defaults_capital_to_100k(tmp_path):
    out = V.run(tmp_path, capital=None, fetch_fn=_market, rank_fn=_rank, engine=FakeEngine(), silent=True)
    state = json.loads(Path(out["state_path"]).read_text(encoding="utf-8"))
    assert state["capital_reference"] == 100000.0


def test_daily_auto_runs_v9_when_flag_is_v9(monkeypatch):
    """ALGO_VERSION = "v9" (production since 2026-09-07): daily.py runs the v9 CLI without --v9."""
    import config
    monkeypatch.setattr(config, "ALGO_VERSION", "v9")
    called = []
    monkeypatch.setattr(daily_mod, "run_screener", lambda universe: 0)
    monkeypatch.setattr(daily_mod, "backup_history_after_run", lambda: None)
    monkeypatch.setattr(daily_mod, "print_tv_instructions", lambda: None)
    monkeypatch.setattr(daily_mod, "maybe_refresh_pnl", lambda x: None)
    monkeypatch.setattr("portfolio_v9.run", lambda *a, **k: called.append(1))
    rc = daily_mod.main(["--skip-screener", "--no-instructions"])
    assert rc == 0 and called == [1]


def test_daily_without_v9_flag_does_not_call_cli(monkeypatch):
    """Under ALGO_VERSION = "v8.4" the ritual is unchanged unless --v9 is passed."""
    import config
    monkeypatch.setattr(config, "ALGO_VERSION", "v8.4")
    called = []
    monkeypatch.setattr(daily_mod, "run_screener", lambda universe: 0)
    monkeypatch.setattr(daily_mod, "backup_history_after_run", lambda: None)
    monkeypatch.setattr(daily_mod, "print_tv_instructions", lambda: None)
    monkeypatch.setattr(daily_mod, "maybe_refresh_pnl", lambda x: None)

    def boom(*a, **k):
        called.append(1)
        raise AssertionError("v9 CLI must not run without --v9 while ALGO_VERSION is v8.4")

    monkeypatch.setattr("portfolio_v9.run", boom)
    rc = daily_mod.main(["--skip-screener", "--no-instructions"])
    assert rc == 0
    assert called == []


def test_daily_v9_flag_invokes_cli(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(daily_mod, "run_screener", lambda universe: 0)
    monkeypatch.setattr(daily_mod, "backup_history_after_run", lambda: None)
    monkeypatch.setattr(daily_mod, "print_tv_instructions", lambda: None)
    monkeypatch.setattr(daily_mod, "maybe_refresh_pnl", lambda x: None)

    def fake_run(capital=None, **k):
        seen["capital"] = capital
        return {"orders": []}

    monkeypatch.setattr("portfolio_v9.run", fake_run)
    rc = daily_mod.main(["--skip-screener", "--no-instructions", "--v9", "--v9-capital", "50000"])
    assert rc == 0
    assert seen["capital"] == 50000.0


def test_gitignore_covers_state_dir():
    root = Path(__file__).resolve().parents[1]
    text = (root / ".gitignore").read_text(encoding="utf-8")
    assert "hydra_screener_local/state/" in text


def test_offdisk_backup_copies_when_env_set(tmp_path, monkeypatch):
    dest = tmp_path / "off"
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(dest))
    V._OFFDISK_WARNED = False
    out = V.run(tmp_path / "state", capital=100000.0, fetch_fn=_market, rank_fn=_rank,
                engine=FakeEngine(), silent=True)
    copied = dest / "state_v9" / "20260904"
    assert (copied / "portfolio_v9.json").exists()
    assert list(copied.glob("instructions_*.md"))
    assert Path(out["state_path"]).exists()


def test_instruction_sheet_shows_interest(tmp_path):
    st = {"capital_reference": 100000, "week_index": 0, "last_renewal_date": None, "pending": [],
          "interest": [
              {"date": "2026-01-06", "since": "2026-01-05", "sleeve": "stocks", "bars": 1, "rate": 0.05, "dollars": 1.0},
              {"date": "2026-01-06", "since": "2026-01-05", "sleeve": "etf", "bars": 1, "rate": 0.05, "dollars": 2.0},
          ]}
    md, js = V.write_instructions(tmp_path, "2026-01-06", [], [], {"total": 100000}, st, "2026-01-07")
    text = md.read_text(encoding="utf-8")
    assert "## Interest" in text
    assert "Cumulative: **3.00** USD" in text
    assert "Since previous run (2026-01-05 -> 2026-01-06)" in text      # covers the previous run -> this run
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["interest"]["cumulative"] == pytest.approx(3.0)


def test_instruction_sheet_interest_zero_without_key(tmp_path):
    md, js = V.write_instructions(
        tmp_path, "2026-09-04", [], [], {"total": 100000},
        {"capital_reference": 100000, "week_index": 0, "last_renewal_date": None, "pending": []},
        "2026-09-07",
    )
    assert "Cumulative: **0.00** USD" in md.read_text(encoding="utf-8")
    assert json.loads(js.read_text(encoding="utf-8"))["interest"]["cumulative"] == 0.0


def test_offdisk_backup_warns_when_env_unset(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("HYDRA_BACKUP_DIR", raising=False)
    V._OFFDISK_WARNED = False
    V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=FakeEngine(), silent=False)
    err = capsys.readouterr().out
    assert "HYDRA_BACKUP_DIR" in err
