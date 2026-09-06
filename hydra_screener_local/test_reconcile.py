"""TASK-351 — reconcile broker CSV vs state. No network, writes nothing."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import reconcile as R  # noqa: E402


def _state():
    return {
        "last_run_date": "2026-09-04",
        "sleeves": {
            "stocks": {"tranches": [
                {"units": {"AAA": 10.0, "BBB": 5.0}, "cash": 1000.0,
                 "last_px": {"AAA": 10.0, "BBB": 20.0}},
                {"units": {}, "cash": 4000.0, "last_px": {}},
            ]},
            "etf": {"tranches": [
                {"units": {"SPY": 2.0}, "cash": 500.0, "last_px": {"SPY": 100.0}},
                {"units": {}, "cash": 4500.0, "last_px": {}},
            ]},
        },
        "interest": [{"dollars": 3.0}],
        "ledger": [{"status": "filled", "cost": 1.25, "side": "buy"}],
        "pending": [{"side": "buy", "dollars": 200.0, "ticker": "CCC"}],
    }


def _csv(tmp_path, rows):
    p = tmp_path / "pos.csv"
    p.write_text("ticker,units\n" + "\n".join(f"{t},{u}" for t, u in rows) + "\n", encoding="utf-8")
    return p


def test_match():
    st = _state()
    broker = {"AAA": 10.0, "BBB": 5.0, "SPY": 2.0}
    rep = R.compare(st, broker, cash_total=10000.0)
    assert rep["n_match"] == 3 and rep["n_missing"] == 0 and rep["n_unknown"] == 0
    assert rep["cash_delta"] == pytest.approx(0.0)
    assert rep["residual"] == pytest.approx(0.0)
    assert rep["explanations"]["pending_buys"] == pytest.approx(200.0)
    assert rep["state_equity"] == pytest.approx(10000.0 + 10*10 + 5*20 + 2*100)


def test_missing_unknown_qty_diff():
    st = _state()
    broker = {"AAA": 9.0, "SPY": 2.0, "ZZZ": 1.0}   # BBB missing, ZZZ unknown, AAA qty-diff
    rep = R.compare(st, broker, cash_total=10000.0)
    kinds = {r["ticker"]: r["kind"] for r in rep["positions"]}
    assert kinds["BBB"] == "missing"
    assert kinds["ZZZ"] == "unknown"
    assert kinds["AAA"] == "quantity-diff"
    assert kinds["SPY"] == "match"
    assert rep["n_missing"] == 1 and rep["n_unknown"] == 1 and rep["n_diff"] == 1


def test_split_cash_accounts():
    st = _state()
    rep = R.compare(st, {"AAA": 10.0, "BBB": 5.0, "SPY": 2.0},
                    cash_stocks=5000.0, cash_etf=5000.0)
    assert rep["cash_mode"] == "split"
    assert rep["broker_cash"]["stocks"] == 5000.0
    assert rep["broker_cash"]["total"] == 10000.0


def test_dividends_absent_are_zero():
    st = _state()
    assert "dividends" not in st
    expl = R.explanations(st)
    assert expl["dividends_recorded"] == 0.0
    assert expl["interest_recorded"] == pytest.approx(3.0)
    assert expl["fees_recorded"] == pytest.approx(1.25)
    assert "pay-date" in expl["note"]


def test_cli_exit_0_on_missing_state(tmp_path):
    csv = _csv(tmp_path, [("AAA", 1)])
    rc = R.main([str(csv), "--cash-total", "1", "--state", str(tmp_path / "nope.json")])
    assert rc == 0


def test_cli_prints_and_writes_nothing(tmp_path, capsys):
    st_path = tmp_path / "portfolio_v9.json"
    st_path.write_text(json.dumps(_state()), encoding="utf-8")
    csv = _csv(tmp_path, [("AAA", 10), ("BBB", 5), ("SPY", 2)])
    before = {p: p.stat().st_mtime for p in tmp_path.iterdir()}
    rc = R.main([str(csv), "--state", str(st_path), "--cash-total", "10000"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "reconcile" in out and "AAA" in out
    after = {p: p.stat().st_mtime for p in tmp_path.iterdir()}
    assert after == before


def test_format_report_lists_kinds():
    rep = R.compare(_state(), {"AAA": 10.0}, cash_total=1.0)
    text = R.format_report(rep)
    assert "missing" in text and "unexplained residual" in text
