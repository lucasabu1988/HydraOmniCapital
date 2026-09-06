"""TASK-363 — splits in the live book (H-003): scaling, idempotency, replay, wiring behind APPLY_SPLITS."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import portfolio_v9 as V  # noqa: E402
from config import V9  # noqa: E402
from core import portfolio_engine as E  # noqa: E402
from core.dividends import apply_dividends, holdings_before  # noqa: E402
from core.splits import apply_splits, summarize_splits  # noqa: E402
from core.state_check import check  # noqa: E402
from test_portfolio_v9_cli import FakeEngine, _market, _rank  # noqa: E402


def _book():
    """8 tranches of 1000; stocks[0] holds AAA 10 @ 20 (bought 09-08, cost 0.2) and BBB 4 @ 50 (cost 0.2)."""
    st = E.new_state(8000.0, "2026-09-04", V9)
    st["last_run_date"] = "2026-09-11"
    tr = st["sleeves"]["stocks"]["tranches"][0]
    tr["units"] = {"AAA": 10.0, "BBB": 4.0}
    tr["last_px"] = {"AAA": 22.0, "BBB": 55.0}
    tr["cash"] = 1000.0 - (200.0 + 0.2) - (200.0 + 0.2)
    st["ledger"] = [
        {"exec_date": "2026-09-08", "sleeve": "stocks", "tranche": 0, "ticker": "AAA", "side": "buy",
         "units": 10.0, "price": 20.0, "dollars": 200.0, "cost": 0.2, "status": "filled"},
        {"exec_date": "2026-09-08", "sleeve": "stocks", "tranche": 0, "ticker": "BBB", "side": "buy",
         "units": 4.0, "price": 50.0, "dollars": 200.0, "cost": 0.2, "status": "filled"},
    ]
    return st


def test_two_for_one_scales_units_and_last_price():
    st = _book()
    new = apply_splits(st, [{"ticker": "AAA", "date": "2026-09-15", "ratio": 2.0}], "2026-09-18")
    tr = st["sleeves"]["stocks"]["tranches"][0]
    assert tr["units"]["AAA"] == pytest.approx(20.0) and tr["last_px"]["AAA"] == pytest.approx(11.0)
    assert tr["units"]["BBB"] == 4.0 and tr["last_px"]["BBB"] == 55.0
    assert len(new) == 1 and new[0]["units_before"] == 10.0 and new[0]["units_after"] == 20.0
    assert st["splits"] == new and summarize_splits(st)["count"] == 1


def test_reverse_split_and_not_held_and_outside_window():
    st = _book()
    new = apply_splits(st, [
        {"ticker": "BBB", "date": "2026-09-16", "ratio": 0.1},          # 1:10 reverse
        {"ticker": "ZZZ", "date": "2026-09-16", "ratio": 2.0},          # not held -> nothing
        {"ticker": "AAA", "date": "2026-09-01", "ratio": 2.0},          # before last_run_date -> ignored
        {"ticker": "AAA", "date": "2026-09-25", "ratio": 3.0},          # after today -> ignored
    ], "2026-09-18")
    tr = st["sleeves"]["stocks"]["tranches"][0]
    assert [r["ticker"] for r in new] == ["BBB"]
    assert tr["units"]["BBB"] == pytest.approx(0.4) and tr["last_px"]["BBB"] == pytest.approx(550.0)
    assert tr["units"]["AAA"] == 10.0


def test_same_split_twice_is_idempotent():
    st = _book()
    table = [{"ticker": "AAA", "date": "2026-09-15", "ratio": 2.0}]
    apply_splits(st, table, "2026-09-18")
    again = apply_splits(st, table, "2026-09-18")
    assert again == [] and st["sleeves"]["stocks"]["tranches"][0]["units"]["AAA"] == pytest.approx(20.0)


def test_fill_after_the_split_is_not_scaled():
    """Split 09-15; a further AAA buy settled 09-16 (post-split units) must stay as booked."""
    st = _book()
    tr = st["sleeves"]["stocks"]["tranches"][0]
    tr["units"]["AAA"] = 10.0 + 6.0
    tr["cash"] -= 6.0 * 11.0
    st["ledger"].append({"exec_date": "2026-09-16", "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
                         "side": "buy", "units": 6.0, "price": 11.0, "dollars": 66.0, "cost": 0.0, "status": "filled"})
    apply_splits(st, [{"ticker": "AAA", "date": "2026-09-15", "ratio": 2.0}], "2026-09-18")
    assert tr["units"]["AAA"] == pytest.approx(20.0 + 6.0)          # only the 10 pre-split units doubled
    assert st["splits"][0]["units_before"] == 10.0


def test_replay_and_holdings_are_split_aware():
    st = _book()
    apply_splits(st, [{"ticker": "AAA", "date": "2026-09-15", "ratio": 2.0}], "2026-09-18")
    assert check(st) == []                                              # ledger replay reproduces 20 units
    held = holdings_before(st, "2026-09-16")
    assert held[("stocks", 0, "AAA")] == pytest.approx(20.0)
    assert holdings_before(st, "2026-09-15")[("stocks", 0, "AAA")] == pytest.approx(10.0)
    # a dividend after the split pays on post-split units
    st["last_run_date"] = "2026-09-18"
    credited = apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-09-22", "dps": 0.5}], "2026-09-25")
    assert credited[0]["units"] == pytest.approx(20.0) and credited[0]["dollars"] == pytest.approx(10.0)


def test_pending_estimates_are_rescaled_but_dollars_untouched():
    st = _book()
    st["pending"] = [{"planned": "2026-09-11", "sleeve": "stocks", "tranche": 1, "ticker": "AAA", "side": "buy",
                      "dollars": 300.0, "est_units": 15.0, "est_price": 20.0}]
    apply_splits(st, [{"ticker": "AAA", "date": "2026-09-15", "ratio": 2.0}], "2026-09-18")
    o = st["pending"][0]
    assert o["dollars"] == 300.0 and o["est_units"] == pytest.approx(30.0) and o["est_price"] == pytest.approx(10.0)


def _second_run(tmp_path, monkeypatch, flag, split_fn):
    import pandas as pd
    V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=FakeEngine(), silent=True)
    st = json.loads((tmp_path / "portfolio_v9.json").read_text(encoding="utf-8"))
    st["last_run_date"] = "2026-09-04"
    st["pending"] = []
    st["sleeves"]["stocks"]["tranches"][0]["units"] = {"AAA": 10.0}
    st["sleeves"]["stocks"]["tranches"][0]["cash"] = 12400.0
    st["ledger"] = [{"exec_date": "2026-09-01", "sleeve": "stocks", "tranche": 0, "ticker": "AAA", "side": "buy",
                     "units": 10.0, "price": 10.0, "dollars": 100.0, "cost": 0.0, "status": "filled"}]
    (tmp_path / "portfolio_v9.json").write_text(json.dumps(st), encoding="utf-8")

    def later(_u=None):
        idx = pd.DatetimeIndex(["2026-09-04", "2026-09-08"])
        m = _market()
        m["prices"] = pd.DataFrame({"AAA": [10.0, 5.0]}, index=idx)
        m["volumes"] = m["prices"] * 1000
        m["spy"] = pd.Series([400.0, 401.0], index=idx)
        m["etf"] = pd.DataFrame({t: [100.0, 101.0] for t in V9["etf_universe"]}, index=idx)
        m["irx"] = pd.Series([5.25, 5.20], index=idx)
        return m

    monkeypatch.setattr(V, "APPLY_SPLITS", flag)
    return V.run(tmp_path, fetch_fn=later, rank_fn=_rank, engine=FakeEngine(), silent=True, split_fn=split_fn)


def test_run_applies_splits_only_when_the_flag_is_on(tmp_path, monkeypatch):
    calls = []

    def table(tickers):
        calls.append(list(tickers))
        return [{"ticker": "AAA", "date": "2026-09-06", "ratio": 2.0}]

    out = _second_run(tmp_path, monkeypatch, False, table)
    assert calls == [] and out["state"]["sleeves"]["stocks"]["tranches"][0]["units"]["AAA"] == 10.0

    out = _second_run(tmp_path / "on", monkeypatch, True, table)
    assert calls and "AAA" in calls[0]
    assert out["state"]["sleeves"]["stocks"]["tranches"][0]["units"]["AAA"] == pytest.approx(20.0)
    assert out["state"]["splits"][0]["ratio"] == 2.0
    sheet = open(out["instructions_md"], encoding="utf-8").read()
    assert "## Splits" in sheet and "AAA x2" in sheet
