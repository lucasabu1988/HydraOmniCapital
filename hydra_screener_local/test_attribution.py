"""TASK-367 — attribution identity on a synthetic two-sleeve book; dashboard + journal carry the block."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analytics_cli  # noqa: E402
import dashboard_v9 as D  # noqa: E402
from analytics.attribution import attribution, diff, positions, render_markdown  # noqa: E402
from core.costbasis import lots_from_ledger  # noqa: E402
from core.journal import build_record  # noqa: E402


def _state():
    """capital 8000 -> 4 x 1000 per sleeve. Events:
    stocks[0]: buy AAA 10 @ 20 (cost 0.20) ; buy BBB 5 @ 40 (cost 0.20) ; sell AAA 4 @ 25 (cost 0.10)
    stocks[1]: DDD written off, proceeds 30 (had 3 units @ 20 bought, cost 0.06)
    etf[0]:    buy SPY 2 @ 100 (cost 0.10) ; dividend SPY 1.50 ; transfer +5 (etf[0]) / -5 (stocks[0])
    interest:  stocks 1.00, etf 0.50 (split by cash weights by the engine; here recorded per sleeve)
    """
    st = {
        "schema_version": 1, "algo_version": "v9", "anchor_date": "2026-09-04", "last_run_date": "2026-09-11",
        "capital_reference": 8000.0,
        "sleeves": {
            "stocks": {"tranches": [
                {"k": 0, "units": {"AAA": 6.0, "BBB": 5.0}, "cash": 1000.0 - (200 + 0.2) - (200 + 0.2) + (100 - 0.1) - 5.0 + 1.0,
                 "last_px": {"AAA": 26.0, "BBB": 38.0}, "stale": {}},
                {"k": 1, "units": {}, "cash": 1000.0 - (60 + 0.06) + 30.0, "last_px": {}, "stale": {}},
                {"k": 2, "units": {}, "cash": 1000.0, "last_px": {}, "stale": {}},
                {"k": 3, "units": {}, "cash": 1000.0, "last_px": {}, "stale": {}},
            ]},
            "etf": {"tranches": [
                {"k": 0, "units": {"SPY": 2.0}, "cash": 1000.0 - (200 + 0.1) + 3.0 + 5.0 + 0.5, "last_px": {"SPY": 110.0}, "stale": {}},
                {"k": 1, "units": {}, "cash": 1000.0, "last_px": {}, "stale": {}},
                {"k": 2, "units": {}, "cash": 1000.0, "last_px": {}, "stale": {}},
                {"k": 3, "units": {}, "cash": 1000.0, "last_px": {}, "stale": {}},
            ]},
        },
        "pending": [],
        "ledger": [
            {"exec_date": "2026-09-08", "sleeve": "stocks", "tranche": 0, "ticker": "AAA", "side": "buy", "units": 10.0, "price": 20.0, "dollars": 200.0, "cost": 0.2, "status": "filled"},
            {"exec_date": "2026-09-08", "sleeve": "stocks", "tranche": 0, "ticker": "BBB", "side": "buy", "units": 5.0, "price": 40.0, "dollars": 200.0, "cost": 0.2, "status": "filled"},
            {"exec_date": "2026-09-08", "sleeve": "stocks", "tranche": 1, "ticker": "DDD", "side": "buy", "units": 3.0, "price": 20.0, "dollars": 60.0, "cost": 0.06, "status": "filled"},
            {"exec_date": "2026-09-08", "sleeve": "etf", "tranche": 0, "ticker": "SPY", "side": "buy", "units": 2.0, "price": 100.0, "dollars": 200.0, "cost": 0.1, "status": "filled"},
            {"exec_date": "2026-09-11", "sleeve": "stocks", "tranche": 0, "ticker": "AAA", "side": "sell", "units": 4.0, "price": 25.0, "dollars": 100.0, "cost": 0.1, "status": "confirmed"},
        ],
        "write_offs": [{"sleeve": "stocks", "tranche": 1, "ticker": "DDD", "proceeds": 30.0, "date": "2026-09-11"}],
        "transfers": [{"date": "2026-09-11", "sleeve": "stocks", "tranche": 0, "dollars": -5.0},
                      {"date": "2026-09-11", "sleeve": "etf", "tranche": 0, "dollars": 5.0}],
        "interest": [{"date": "2026-09-11", "since": "2026-09-04", "sleeve": "stocks", "bars": 5, "rate": 0.04, "dollars": 1.0},
                     {"date": "2026-09-11", "since": "2026-09-04", "sleeve": "etf", "bars": 5, "rate": 0.04, "dollars": 0.5}],
        "dividends": [{"ex_date": "2026-09-10", "sleeve": "etf", "tranche": 0, "ticker": "SPY", "units": 2.0, "dps": 1.5, "dollars": 3.0}],
    }
    return st


def test_identity_components_sum_to_the_change():
    a = attribution(_state())
    b = a["book"]
    total_value = sum(tr["cash"] for s in _state()["sleeves"].values() for tr in s["tranches"]) \
        + 6 * 26.0 + 5 * 38.0 + 2 * 110.0
    assert b["value"] == pytest.approx(total_value)
    assert b["change"] == pytest.approx(total_value - 8000.0)
    assert abs(b["identity_gap"]) < 1e-9
    assert b["transfers_net_zero"] and b["transfers"] == pytest.approx(0.0)
    assert abs(b["residual"]) < 1e-9                       # the fixture is accounting-consistent
    # components by hand
    stocks_trading = (6 * 26.0 + 5 * 38.0) + 100.0 + 30.0 - (200 + 200 + 60)      # MV + sells + write-off - buys
    assert b["selection"] == pytest.approx(stocks_trading)
    assert b["etf"] == pytest.approx(2 * 110.0 - 200.0)
    assert b["fees"] == pytest.approx(-(0.2 + 0.2 + 0.06 + 0.1 + 0.1))
    assert b["interest"] == pytest.approx(1.5) and b["dividends"] == pytest.approx(3.0)
    assert a["sleeves"]["stocks"]["transfers"] == pytest.approx(-5.0)
    assert a["sleeves"]["etf"]["transfers"] == pytest.approx(5.0)


def test_residual_shows_an_unexplained_cash_edit():
    st = _state()
    st["sleeves"]["stocks"]["tranches"][2]["cash"] += 7.0
    a = attribution(st)
    assert a["book"]["residual"] == pytest.approx(7.0)
    assert abs(a["book"]["identity_gap"]) < 1e-9


def test_positions_and_average_cost_rule():
    pos = {(p["sleeve"], p["ticker"]): p for p in positions(_state())}
    aaa = pos[("stocks", "AAA")]
    assert aaa["units"] == 6.0 and aaa["avg_cost"] == pytest.approx(20.0)
    assert aaa["realised"] == pytest.approx((25.0 - 20.0) * 4)            # confirmed sell counts
    assert aaa["unrealised"] == pytest.approx((26.0 - 20.0) * 6)
    ddd = pos[("stocks", "DDD")]                                            # closed by write-off, realised only
    assert ddd["units"] == 0.0 and ddd["realised"] == pytest.approx(30.0 - 60.0)
    lots = lots_from_ledger(_state(), statuses=("filled",))                 # narrowed on purpose: "filled" only
    assert lots[("stocks", 0, "AAA")]["qty"] == 10.0


def test_marks_override_last_px():
    a = attribution(_state(), marks={"stocks": {"AAA": 30.0, "BBB": 38.0}, "etf": {"SPY": 110.0}})
    assert a["book"]["selection"] == pytest.approx((6 * 30.0 + 5 * 38.0) + 100.0 + 30.0 - 460.0)


def test_weekly_diff_and_markdown():
    a = attribution(_state())
    prev = json.loads(json.dumps(a, default=str))
    prev["book"]["interest"] -= 0.5
    prev["book"]["change"] -= 0.5
    prev["book"]["value"] -= 0.5
    d = diff(prev, a)
    assert d["interest"] == pytest.approx(0.5) and d["selection"] == pytest.approx(0.0)
    md = render_markdown(a, d)
    assert "| interest |" in md and "stock selection" in md and "identity gap" in md
    assert diff(None, a) is None


def test_dashboard_uses_the_shared_cost_basis_and_exposes_attribution():
    st = _state()
    snap = D.build_snapshot(st, quotes={})
    # The dashboard walks the canonical projection (R-108), not a narrowed status set.
    assert D._lots_from_ledger is lots_from_ledger or D._lots_from_ledger(st) == lots_from_ledger(st)
    assert "attribution" in snap and abs(snap["attribution"]["book"]["identity_gap"]) < 1e-9
    assert "positions" not in snap["attribution"]                          # slim block for the browser


def test_journal_record_carries_the_block():
    rec = build_record(date="2026-09-11", state=_state())
    assert rec["attribution"]["book"]["interest"] == pytest.approx(1.5)
    assert "positions" not in rec["attribution"]
    rec2 = build_record(date="2026-09-11", state={})
    assert rec2["attribution"] is None


def test_cli_writes_csv_and_markdown(tmp_path):
    sd = tmp_path / "state"
    sd.mkdir()
    (sd / "portfolio_v9.json").write_text(json.dumps(_state()), encoding="utf-8")
    rc = analytics_cli.main(["--state-dir", str(sd)])
    assert rc == 0
    out = sd / "analytics"
    assert (out / "attribution_20260911.csv").exists() and (out / "ATTRIBUTION.md").exists()
    rows = (out / "attribution_20260911.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("sleeve,tranche,ticker") and len(rows) >= 4
    assert json.loads((sd / "portfolio_v9.json").read_text(encoding="utf-8")) == _state()   # read-only
