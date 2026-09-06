"""TASK-342 — dashboard snapshot arithmetic. No network."""
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core.portfolio_engine as E  # noqa: E402
import dashboard_v9 as D  # noqa: E402
from config import V9  # noqa: E402

CFG = dict(V9, tranches=2, step_bars=1, hold_bars=2, stock_cost_bp=10.0, etf_cost_bp=0.0)


def _state():
    """Buy 10 AAA @ 10 (fee 1), partial sell 4 @ 12 (fee 0.48), not_filled BBB, transfer cash."""
    return {
        "schema_version": 1,
        "algo_version": "v9",
        "anchor_date": "2026-01-05",
        "last_run_date": "2026-01-06",
        "capital_reference": 800.0,
        "week_index": 0,
        "sleeves": {
            "stocks": {"tranches": [
                {"k": 0, "opened": "2026-01-05", "units": {"AAA": 6.0}, "cash": 100.0,
                 "last_px": {"AAA": 10.0}},
                {"k": 1, "opened": None, "units": {}, "cash": 200.0, "last_px": {}},
            ]},
            "etf": {"tranches": [
                {"k": 0, "opened": "2026-01-05", "units": {}, "cash": 250.0, "last_px": {}},
                {"k": 1, "opened": None, "units": {}, "cash": 200.0, "last_px": {}},
            ]},
        },
        "pending": [{"planned": "2026-01-06", "sleeve": "stocks", "tranche": 1,
                     "side": "buy", "ticker": "CCC", "dollars": 50.0, "est_units": 5.0,
                     "est_price": 10.0}],
        "ledger": [
            {"exec_date": "2026-01-06", "sleeve": "stocks", "tranche": 0, "side": "buy",
             "ticker": "AAA", "units": 10.0, "price": 10.0, "dollars": 100.0, "cost": 1.0,
             "status": "filled"},
            {"exec_date": "2026-01-06", "sleeve": "stocks", "tranche": 0, "side": "sell",
             "ticker": "AAA", "units": 4.0, "price": 12.0, "dollars": 48.0, "cost": 0.48,
             "status": "filled"},
            {"exec_date": "2026-01-06", "sleeve": "stocks", "tranche": 0, "side": "buy",
             "ticker": "BBB", "units": None, "price": None, "dollars": 20.0, "cost": None,
             "status": "not_filled"},
            {"exec_date": "2026-01-06", "sleeve": "etf", "tranche": 0, "side": "park",
             "ticker": "TBILL", "status": "noted"},
        ],
        "transfers": [{"date": "2026-01-06", "sleeve": "etf", "tranche": 0, "dollars": 50.0}],
        "write_offs": [],
    }


def test_average_cost_partial_sell_and_not_filled():
    # avg stays 10 after selling 4 of 10; remaining 6; realised (12-10)*4 = 8
    snap = D.build_snapshot(_state(), {"AAA": 11.0}, spy=400.0)
    assert snap["ok"]
    pos = next(p for p in snap["positions"] if p["ticker"] == "AAA")
    assert pos["units"] == pytest.approx(6.0)
    assert pos["avg_cost"] == pytest.approx(10.0)
    assert pos["last"] == pytest.approx(11.0)
    assert pos["market_value"] == pytest.approx(66.0)
    assert pos["unrealised"] == pytest.approx(6.0)          # (11-10)*6
    assert pos["realised"] == pytest.approx(8.0)
    assert pos["fees"] == pytest.approx(1.48)
    assert not any(p["ticker"] == "BBB" for p in snap["positions"])
    log_status = {r["ticker"]: r["status"] for r in snap["trade_log"]}
    assert log_status["BBB"] == "not_filled"
    assert log_status["TBILL"] == "noted"
    assert snap["transfers"] and snap["pending"][0]["ticker"] == "CCC"
    # cash 100+200+250+200 = 750; invested 66; total 816
    assert snap["cash"] == pytest.approx(750.0)
    assert snap["invested"] == pytest.approx(66.0)
    assert snap["total"] == pytest.approx(816.0)
    assert snap["sleeves"]["stocks"]["share"] == pytest.approx((100 + 200 + 66) / 816)
    assert snap["banner"].startswith("fills presumidos")


def test_reconciles_with_summary_table():
    st = _state()
    quotes = {"AAA": 11.0}
    snap = D.build_snapshot(st, quotes, spy=400.0)
    px_s = pd.Series({"AAA": 11.0})
    px_e = pd.Series({"SPY": 400.0})
    sumry = E.summary_table(st, px_s, px_e, CFG)
    assert snap["total"] == pytest.approx(sumry["total"])
    assert snap["sleeves"]["stocks"]["value"] == pytest.approx(sumry["sleeves"]["stocks"]["value"])
    assert snap["sleeves"]["etf"]["value"] == pytest.approx(sumry["sleeves"]["etf"]["value"])
    assert snap["sleeves"]["stocks"]["cash"] == pytest.approx(sumry["sleeves"]["stocks"]["cash"])


def test_stale_quote_fallback_to_last_px():
    st = _state()
    snap = D.build_snapshot(st, quotes={}, spy=None)          # no live quotes
    pos = next(p for p in snap["positions"] if p["ticker"] == "AAA")
    assert pos["last"] == pytest.approx(10.0)
    assert pos["stale"] is True
    assert pos["market_value"] == pytest.approx(60.0)


def test_fetch_quotes_marks_stale_on_failure(monkeypatch):
    import types

    def boom(*a, **k):
        raise RuntimeError("no net")

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=boom))
    q = D.fetch_quotes(["AAA", "SPY"], fallback={"AAA": 9.5})
    assert q["AAA"]["price"] == pytest.approx(9.5)
    assert q["AAA"]["stale"] is True
    assert q["SPY"]["stale"] is True


def test_equity_curve_append_is_idempotent_per_timestamp(tmp_path):
    p = tmp_path / "equity_curve.csv"
    row = {"timestamp": "2026-01-06T20:00:00Z", "total": "800", "stocks": "400",
           "etf": "400", "cash": "800", "spy_close": "400"}
    assert D.append_curve(p, row) is True
    assert D.append_curve(p, row) is False
    rows = D.read_curve(p)
    assert len(rows) == 1
    row2 = dict(row, timestamp="2026-01-06T20:05:00Z", total="801")
    assert D.append_curve(p, row2) is True
    assert len(D.read_curve(p)) == 2


def test_annotate_day_pnl_and_vs_spy():
    snap = {"total": 110.0, "as_of": "2026-01-07T12:00:00Z",
            "since_inception_pct": 0.10, "spy": {"price": 440.0, "stale": False}}
    curve = [
        {"timestamp": "2026-01-05T21:00:00Z", "total": "100", "spy_close": "400"},
        {"timestamp": "2026-01-06T21:00:00Z", "total": "105", "spy_close": "410"},
    ]
    D.annotate_performance(snap, curve)
    assert snap["day_pnl_usd"] == pytest.approx(5.0)          # vs 06-01 last
    assert snap["vs_spy_pct"] == pytest.approx(440 / 400 - 1)
    assert len(snap["curve"]) == 2
