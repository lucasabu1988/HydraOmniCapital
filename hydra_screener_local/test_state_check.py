"""TASK-360 — ledger replay and migrations. Synthetic state, no network."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402
import verify_state as VS  # noqa: E402
from config import V9  # noqa: E402
import core.portfolio_engine as E  # noqa: E402
from core.state_check import check, replay  # noqa: E402
from core.state_migrations import SchemaError, migrate  # noqa: E402


def _state(capital=800.0):
    half = capital / 2.0
    k = 2
    each = half / k
    tr = lambda i: {"k": i, "opened": None, "units": {}, "cash": each, "last_px": {}, "stale": {}}
    return {
        "schema_version": 1,
        "capital_reference": capital,
        "last_run_date": "2026-01-10",
        "sleeves": {
            "stocks": {"tranches": [tr(0), tr(1)]},
            "etf": {"tranches": [tr(0), tr(1)]},
        },
        "pending": [],
        "ledger": [],
        "write_offs": [],
        "transfers": [],
        "interest": [],
        "dividends": [],
    }


def test_replay_matches_new_book():
    st = _state()
    rec = replay(st)
    assert rec["stocks"]["tranches"][0]["cash"] == pytest.approx(200.0)
    assert rec["etf"]["tranches"][1]["cash"] == pytest.approx(200.0)
    assert check(st) == []


def test_replay_buy_sell_cost_and_transfer():
    st = _state()
    st["ledger"] = [
        {"exec_date": "2026-01-06", "sleeve": "stocks", "tranche": 0, "side": "buy",
         "ticker": "AAA", "units": 10.0, "price": 10.0, "dollars": 100.0, "cost": 0.2,
         "status": "filled"},
        {"exec_date": "2026-01-07", "sleeve": "stocks", "tranche": 0, "side": "sell",
         "ticker": "AAA", "units": 4.0, "price": 12.0, "dollars": 48.0, "cost": 0.1,
         "status": "filled"},
    ]
    st["transfers"] = [
        {"date": "2026-01-06", "sleeve": "stocks", "tranche": 0, "dollars": -20.0},
        {"date": "2026-01-06", "sleeve": "etf", "tranche": 0, "dollars": 20.0},
    ]
    rec = replay(st)
    # stocks[0]: 200 - 20 transfer - 100.2 buy + 47.9 sell = 127.7; units AAA=6
    assert rec["stocks"]["tranches"][0]["cash"] == pytest.approx(127.7)
    assert rec["stocks"]["tranches"][0]["units"]["AAA"] == pytest.approx(6.0)
    assert rec["etf"]["tranches"][0]["cash"] == pytest.approx(220.0)
    st["sleeves"]["stocks"]["tranches"][0]["cash"] = 127.7
    st["sleeves"]["stocks"]["tranches"][0]["units"] = {"AAA": 6.0}
    st["sleeves"]["etf"]["tranches"][0]["cash"] = 220.0
    assert check(st) == []


def test_replay_interest_dividend_writeoff():
    st = _state()
    st["sleeves"]["stocks"]["tranches"][0]["units"] = {"AAA": 10.0}
    st["sleeves"]["stocks"]["tranches"][0]["cash"] = 100.0
    st["ledger"] = [{
        "exec_date": "2026-01-06", "sleeve": "stocks", "tranche": 0, "side": "buy",
        "ticker": "AAA", "units": 10.0, "price": 10.0, "dollars": 100.0, "cost": 0.0,
        "status": "filled",
    }]
    # after buy: cash 100, units 10. dividend +5; interest +1 on that tranche
    # write-off AAA proceeds 80
    st["dividends"] = [{"ex_date": "2026-01-08", "sleeve": "stocks", "tranche": 0,
                        "ticker": "AAA", "dollars": 5.0}]
    st["interest"] = [{"date": "2026-01-08", "sleeve": "stocks", "dollars": 1.0}]
    st["write_offs"] = [{"date": "2026-01-09", "sleeve": "stocks", "tranche": 0,
                         "ticker": "AAA", "proceeds": 80.0}]
    rec = replay(st)
    t0 = rec["stocks"]["tranches"][0]
    assert "AAA" not in t0["units"]
    # 200 - 100 buy + 5 div = 105; interest $1 split 105:200; write-off +80
    assert t0["cash"] == pytest.approx(200.0 - 100.0 + 5.0 + 1.0 * 105.0 / 305.0 + 80.0)
    st["sleeves"]["stocks"]["tranches"][0]["cash"] = t0["cash"]
    st["sleeves"]["stocks"]["tranches"][0]["units"] = {}
    st["sleeves"]["stocks"]["tranches"][1]["cash"] = rec["stocks"]["tranches"][1]["cash"]
    assert check(st) == []


def test_check_flags_replay_gap_and_pending_and_schema():
    st = _state()
    st["sleeves"]["stocks"]["tranches"][0]["cash"] = 50.0  # should be 200
    findings = {f.code: f for f in check(st)}
    assert findings["replay_cash"].level == "ERROR"
    st = _state()
    st["pending"] = [{"sleeve": "stocks", "tranche": 9, "ticker": "AAA", "side": "buy", "dollars": 10}]
    assert any(f.code == "pending_tranche" for f in check(st))
    st = _state()
    st["pending"] = [{"sleeve": "stocks", "tranche": 0, "ticker": "aaa", "side": "buy"}]
    codes = {f.code for f in check(st)}
    assert "pending_qty" in codes
    assert "ticker_case" in codes
    st = _state()
    st["schema_version"] = 99
    findings = check(st)
    assert findings and findings[0].code == "schema"


def test_migrate_fills_keys_and_refuses_unknown():
    st = {"schema_version": 1, "sleeves": {"stocks": {"tranches": [{"k": 0, "units": {"A": 1.0}, "cash": 1.0}]}}}
    out = migrate(st)
    assert out["schema_version"] == 1
    assert out["interest"] == [] and out["dividends"] == []
    assert out["sleeves"]["stocks"]["tranches"][0]["stale"] == {}
    migrate(out)
    assert out["schema_version"] == 1
    with pytest.raises(SchemaError, match="unknown schema_version 7"):
        migrate({"schema_version": 7})


def test_post_settle_ledger_may_be_after_last_run_date():
    """TASK-369: settle books t+1 while last_run_date is still the plan date t.

    JSON round-trip + check must be clean (no ERROR) on that in-between state.
    """
    cfg = dict(V9, tranches=2, step_bars=1, hold_bars=2, stock_cost_bp=0.0, etf_cost_bp=0.0)
    dates = pd.bdate_range("2026-01-05", periods=4)
    st = E.new_state(800.0, str(dates[0].date()), cfg)
    stock = pd.DataFrame({"A": [10.0, 10.0, 10.0, 10.0]}, index=dates)
    etf = pd.DataFrame({"SPY": [1.0, 1.0, 1.0, 1.0]}, index=dates)
    rk = pd.DataFrame({
        "ticker": ["A"], "rank": [1], "sector": ["Other"],
        "reason": [""], "recommended_count": 1, "recommended": [True],
    })
    st, _ = E.plan(st, str(dates[0].date()), rk, stock.iloc[:1], etf.iloc[:1], 0.0, cfg)
    assert st["pending"]
    E.settle(st, str(dates[1].date()), stock.iloc[1], etf.iloc[1], cfg)
    assert st["pending"] == []
    assert st["last_run_date"] == str(dates[0].date())
    assert st["ledger"]
    assert str(st["ledger"][0].get("exec_date")) == str(dates[1].date())
    rt = json.loads(json.dumps(st))
    errors = [f for f in check(rt) if f.level == "ERROR"]
    assert errors == [], errors
    # still a real error if a future fill is sitting next to un-settled pending
    st["pending"] = [{"sleeve": "stocks", "tranche": 0, "ticker": "A", "side": "buy", "dollars": 1}]
    codes = {f.code for f in check(st) if f.level == "ERROR"}
    assert "ledger_future" in codes
    st["pending"] = []
    # or if the fill was not planned on last_run_date (corruption, not a t+1 settle)
    st["ledger"][0]["planned"] = "2020-01-01"
    codes = {f.code for f in check(st) if f.level == "ERROR"}
    assert "ledger_future" in codes


def test_cli_clean_and_restore_requires_yes(tmp_path, capsys):
    st = _state()
    path = tmp_path / "portfolio_v9.json"
    path.write_text(json.dumps(st), encoding="utf-8")
    rc = VS.main(["--state", str(path)])
    assert rc == 0
    assert "clean" in capsys.readouterr().out
    other = tmp_path / "backup.json"
    other.write_text(json.dumps(st), encoding="utf-8")
    rc = VS.main(["--state", str(path), "--restore", str(other)])
    assert rc == 2
    assert "refused" in capsys.readouterr().out
    rc = VS.main(["--state", str(path), "--restore", str(other), "--yes"])
    assert rc == 0
    kept = list((tmp_path / "backup").glob("*_replaced.json"))
    assert len(kept) == 1
