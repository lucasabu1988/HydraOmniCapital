"""TASK-349 — cash dividends in the live book. Fake table, no network."""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core.dividends as D  # noqa: E402
import data.dividends as DD  # noqa: E402
import dashboard_v9 as Dash  # noqa: E402
import portfolio_v9 as V  # noqa: E402
from test_portfolio_v9_cli import FakeEngine, _market, _rank  # noqa: E402


def _state():
    return {
        "last_run_date": "2026-01-05",
        "sleeves": {
            "stocks": {"tranches": [
                {"k": 0, "cash": 100.0, "units": {"AAA": 10.0}, "last_px": {"AAA": 10.0}},
                {"k": 1, "cash": 200.0, "units": {}, "last_px": {}},
            ]},
            "etf": {"tranches": [
                {"k": 0, "cash": 50.0, "units": {"TLT": 4.0}, "last_px": {"TLT": 90.0}},
                {"k": 1, "cash": 50.0, "units": {}, "last_px": {}},
            ]},
        },
        "ledger": [
            {"exec_date": "2026-01-02", "sleeve": "stocks", "tranche": 0, "side": "buy",
             "ticker": "AAA", "units": 10.0, "status": "filled"},
            {"exec_date": "2026-01-02", "sleeve": "etf", "tranche": 0, "side": "buy",
             "ticker": "TLT", "units": 4.0, "status": "filled"},
        ],
        "write_offs": [],
    }


def test_credits_units_times_dps_to_holding_tranche():
    st = _state()
    table = [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 0.50},
             {"ticker": "TLT", "ex_date": "2026-01-08", "dps": 0.25}]
    new = D.apply_dividends(st, table, today="2026-01-10")
    assert len(new) == 2
    assert st["sleeves"]["stocks"]["tranches"][0]["cash"] == pytest.approx(105.0)  # 10 * 0.50
    assert st["sleeves"]["etf"]["tranches"][0]["cash"] == pytest.approx(51.0)     # 4 * 0.25
    rec = {r["ticker"]: r for r in st["dividends"]}
    assert rec["AAA"]["ex_date"] == "2026-01-08"
    assert rec["AAA"]["units"] == pytest.approx(10.0)
    assert rec["AAA"]["dollars"] == pytest.approx(5.0)


def test_units_on_ex_date_not_current_units():
    """Bought 10 on 01-02, sold 4 on 01-09; ex-date 01-08 still pays on 10."""
    st = _state()
    st["ledger"].append({"exec_date": "2026-01-09", "sleeve": "stocks", "tranche": 0,
                         "side": "sell", "ticker": "AAA", "units": 4.0, "status": "filled"})
    st["sleeves"]["stocks"]["tranches"][0]["units"]["AAA"] = 6.0
    D.apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 1.0}], "2026-01-10")
    rec = st["dividends"][0]
    assert rec["units"] == pytest.approx(10.0)
    assert rec["dollars"] == pytest.approx(10.0)


def test_buy_on_ex_date_does_not_get_the_dividend():
    st = _state()
    st["ledger"] = [{"exec_date": "2026-01-08", "sleeve": "stocks", "tranche": 0,
                     "side": "buy", "ticker": "AAA", "units": 10.0, "status": "filled"}]
    new = D.apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 1.0}], "2026-01-10")
    assert new == []
    assert st["sleeves"]["stocks"]["tranches"][0]["cash"] == pytest.approx(100.0)


def test_idempotent_on_ex_date_sleeve_tranche_ticker():
    st = _state()
    table = [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 0.50}]
    a = D.apply_dividends(st, table, "2026-01-10")
    b = D.apply_dividends(st, table, "2026-01-10")
    assert len(a) == 1 and b == []
    assert st["sleeves"]["stocks"]["tranches"][0]["cash"] == pytest.approx(105.0)
    assert len(st["dividends"]) == 1


def test_first_run_without_last_run_credits_nothing():
    st = _state()
    st["last_run_date"] = None
    new = D.apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 1.0}], "2026-01-10")
    assert new == []


def test_ex_date_on_or_before_last_run_skipped():
    st = _state()
    new = D.apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-01-05", "dps": 1.0}], "2026-01-10")
    assert new == []


def test_summarize_missing_key_is_zero():
    s = D.summarize_dividends({})
    assert s["cumulative"] == 0.0
    assert s["since_last_run"] == 0.0


def test_fetch_dividends_uses_cache_and_patches_yahoo(tmp_path, monkeypatch):
    cache = tmp_path / "dividends_cache.json"
    monkeypatch.setattr(DD, "CACHE_FILE", str(cache))
    monkeypatch.setattr(DD, "DATA_CACHE_DIR", str(tmp_path))

    class FakeTicker:
        def __init__(self, t):
            self.t = t

        @property
        def dividends(self):
            return pd.Series([0.42], index=pd.DatetimeIndex(["2026-03-01"]))

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)
    rows = DD.fetch_dividends(["TLT"])
    assert len(rows) == 1
    assert rows[0]["ticker"] == "TLT" and rows[0]["ex_date"] == "2026-03-01"
    assert rows[0]["dps"] == pytest.approx(0.42)
    assert cache.exists()

    def boom(t):
        raise RuntimeError("network")

    monkeypatch.setattr("yfinance.Ticker", boom)
    rows2 = DD.fetch_dividends(["TLT"])
    assert rows2[0]["dps"] == pytest.approx(0.42)


def test_tickers_from_state_skips_old_ledger_names():
    st = _state()
    st["ledger"].append({"exec_date": "2025-06-01", "sleeve": "stocks", "tranche": 0,
                         "side": "buy", "ticker": "OLD", "units": 1.0, "status": "filled"})
    st["ledger"].append({"exec_date": "2026-01-09", "sleeve": "stocks", "tranche": 0,
                         "side": "sell", "ticker": "ZZZ", "units": 1.0, "status": "filled"})
    names = D.tickers_from_state(st)
    assert "AAA" in names and "TLT" in names and "SPY" in names   # held + ETF universe
    assert "OLD" not in names                                      # sold long before last_run
    assert "ZZZ" in names                                          # fill after last_run_date


def test_fetch_skips_ticker_refreshed_today(tmp_path, monkeypatch):
    cache = tmp_path / "dividends_cache.json"
    monkeypatch.setattr(DD, "CACHE_FILE", str(cache))
    monkeypatch.setattr(DD, "DATA_CACHE_DIR", str(tmp_path))
    calls = []

    class FakeTicker:
        def __init__(self, t):
            calls.append(t)

        @property
        def dividends(self):
            return pd.Series([0.1], index=pd.DatetimeIndex(["2026-03-01"]))

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)
    r = {}
    DD.fetch_dividends(["TLT"], report=r)
    assert calls == ["TLT"] and r["downloaded"] == 1
    r2 = {}
    DD.fetch_dividends(["TLT"], report=r2)
    assert calls == ["TLT"]                    # second call same UTC day: no download
    assert r2["downloaded"] == 0 and r2["skipped_fresh"] == ["TLT"]


def test_dashboard_kpi_and_log():
    from test_dashboard_v9 import _state as dash_state
    st = dash_state()
    st["dividends"] = [
        {"date": "2026-01-10", "since": "2026-01-05", "ex_date": "2026-01-08",
         "sleeve": "etf", "tranche": 0, "ticker": "TLT", "units": 4.0, "dps": 0.25, "dollars": 1.0},
        {"date": "2026-01-10", "since": "2026-01-05", "ex_date": "2026-01-08",
         "sleeve": "stocks", "tranche": 0, "ticker": "AAA", "units": 10.0, "dps": 0.5, "dollars": 5.0},
    ]
    snap = Dash.build_snapshot(st, {"AAA": 11.0}, spy=400.0)
    assert snap["dividends"] == pytest.approx(6.0)
    rows = [r for r in snap["trade_log"] if r["side"] == "dividend"]
    assert len(rows) == 2
    assert {r["ticker"] for r in rows} == {"TLT", "AAA"}
    assert Dash.build_snapshot(dash_state(), {"AAA": 11.0}, spy=400.0)["dividends"] == 0.0


def test_sheet_shows_dividends(tmp_path):
    st = {"capital_reference": 100000, "week_index": 0, "last_renewal_date": None, "pending": [],
          "dividends": [
              {"date": "2026-01-10", "since": "2026-01-05", "ex_date": "2026-01-08",
               "sleeve": "etf", "tranche": 0, "ticker": "TLT", "units": 4, "dps": 0.25, "dollars": 1.0},
              {"date": "2026-01-10", "since": "2026-01-05", "ex_date": "2026-01-08",
               "sleeve": "stocks", "tranche": 0, "ticker": "AAA", "units": 10, "dps": 0.5, "dollars": 5.0},
          ]}
    md, js = V.write_instructions(tmp_path, "2026-01-10", [], [], {"total": 100000}, st, "2026-01-13")
    text = md.read_text(encoding="utf-8")
    assert "## Dividends" in text
    assert "Cumulative: **6.00** USD" in text
    assert "pay-date" in text
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["dividends"]["cumulative"] == pytest.approx(6.0)


def test_run_credits_before_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))
    # first run: no last_run, nothing credited
    V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank,
          engine=FakeEngine(), silent=True)
    state = json.loads((tmp_path / "portfolio_v9.json").read_text(encoding="utf-8"))
    state["last_run_date"] = "2026-09-04"
    state["sleeves"]["stocks"]["tranches"][0]["units"] = {"AAA": 10.0}
    state["sleeves"]["stocks"]["tranches"][0]["cash"] = 1000.0
    state["ledger"] = [{"exec_date": "2026-09-01", "sleeve": "stocks", "tranche": 0,
                        "side": "buy", "ticker": "AAA", "units": 10.0, "status": "filled"}]
    (tmp_path / "portfolio_v9.json").write_text(json.dumps(state), encoding="utf-8")

    def later(_u=None):
        idx = pd.DatetimeIndex(["2026-09-04", "2026-09-08"])
        m = _market()
        m["prices"] = pd.DataFrame({"AAA": [10.0, 10.0]}, index=idx)
        m["volumes"] = m["prices"] * 1000
        m["spy"] = pd.Series([400.0, 401.0], index=idx)
        from config import V9
        m["etf"] = pd.DataFrame({t: [100.0, 101.0] for t in V9["etf_universe"]}, index=idx)
        m["irx"] = pd.Series([5.25, 5.20], index=idx)
        return m

    def table(_tickers):
        return [{"ticker": "AAA", "ex_date": "2026-09-05", "dps": 0.40}]

    cash_before = state["sleeves"]["stocks"]["tranches"][0]["cash"]
    out = V.run(tmp_path, fetch_fn=later, rank_fn=_rank, engine=FakeEngine(),
                silent=True, dividend_fn=table)
    after = json.loads(Path(out["state_path"]).read_text(encoding="utf-8"))
    assert after["sleeves"]["stocks"]["tranches"][0]["cash"] == pytest.approx(cash_before + 4.0)
    assert after["dividends"][0]["dollars"] == pytest.approx(4.0)


def test_fetch_report_separates_no_dividends_from_failed(monkeypatch, tmp_path):
    """TASK-385: an empty list after a successful fetch is 'no dividends'; a failed fetch is not."""
    import data.dividends as DD
    monkeypatch.setattr(DD, "CACHE_FILE", str(tmp_path / "div.json"))

    class Tk:
        def __init__(self, t):
            self.t = t

        @property
        def dividends(self):
            if self.t == "FAIL":
                raise RuntimeError("Too Many Requests")
            if self.t == "NONE":
                return pd.Series(dtype=float)
            return pd.Series([0.5], index=pd.DatetimeIndex(["2026-06-01"]))

    monkeypatch.setitem(sys.modules, "yfinance", type("yf", (), {"Ticker": staticmethod(Tk)}))
    rep = {}
    rows = DD.fetch_dividends(["PAYS", "NONE", "FAIL"], report=rep)
    assert [r["ticker"] for r in rows] == ["PAYS"]
    assert rep["failed_tickers"] == ["FAIL"] and rep["no_dividends"] == ["NONE"]
    cov = DD.coverage(["PAYS", "NONE", "FAIL"])
    assert cov["fresh"] == ["PAYS", "NONE"] and cov["missing"] == ["FAIL"]
