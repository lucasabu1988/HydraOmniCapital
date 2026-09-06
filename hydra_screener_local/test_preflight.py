"""TASK-352 — preflight checks. No network: frames are synthetic."""
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import preflight as PF  # noqa: E402
import portfolio_v9 as V  # noqa: E402
from config import V9  # noqa: E402
from test_portfolio_v9_cli import FakeEngine, _market, _rank  # noqa: E402

ETF = list(V9["etf_universe"])
IDX = pd.DatetimeIndex(["2026-09-03", "2026-09-04"])  # Thu, Fri


def _frames(stock_last="2026-09-04", etf_last="2026-09-04", irx_last="2026-09-04",
            n_stocks=10, missing_last=0, drop_etf=None, etf_nan=None):
    dates = pd.DatetimeIndex(["2026-09-03", "2026-09-04"])
    prices = pd.DataFrame(
        {f"T{i}": [10.0, 10.0] for i in range(n_stocks)}, index=dates,
    )
    if missing_last:
        for i in range(missing_last):
            prices.iloc[-1, i] = float("nan")
    if stock_last != "2026-09-04":
        prices = prices.iloc[:1]
        prices.index = pd.DatetimeIndex([stock_last])
    etf = pd.DataFrame({t: [100.0, 101.0] for t in ETF}, index=dates)
    if drop_etf:
        etf = etf.drop(columns=list(drop_etf))
    if etf_nan:
        for t in etf_nan:
            etf.loc[etf.index[-1], t] = float("nan")
    if etf_last != stock_last and etf_last != "2026-09-04":
        etf = etf.iloc[:1]
        etf.index = pd.DatetimeIndex([etf_last])
    elif etf_last != "2026-09-04":
        etf = etf.copy()
        etf.index = pd.DatetimeIndex([etf.index[0], etf_last])
    irx = pd.Series([5.0, 5.1], index=dates)
    if irx_last != "2026-09-04":
        irx = irx.iloc[:1]
        irx.index = pd.DatetimeIndex([irx_last])
    ranking = pd.DataFrame({
        "ticker": [f"T{i}" for i in range(n_stocks)],
        "rank": range(1, n_stocks + 1),
        "sector": ["Technology"] * n_stocks,
        "recommended": [True] * min(5, n_stocks) + [False] * max(0, n_stocks - 5),
        "recommended_count": 5,
    })
    # A stub book, but a valid one: preflight now replays the state (TASK-360) through
    # core.state_check, which rejects a missing capital_reference as non-finite (audit
    # phase 2). A fixture without it would be testing a state the engine cannot produce.
    state = {"schema_version": 1, "pending": [], "capital_reference": 100000.0}
    return prices, etf, irx, ranking, state


def _statuses(result):
    return {r["check"]: r["status"] for r in result["rows"]}


def test_all_ok_matching_friday():
    prices, etf, irx, ranking, state = _frames()
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    asof="2026-09-04", last_session="2026-09-04",
                    backup_dir="/tmp/backup")
    assert r["ok"] and not r["hard"]
    st = _statuses(r)
    assert st["last bars"] == "OK"
    assert st["universe print share"] == "OK"
    assert st["ETFs present"] == "OK"
    assert st["sector-unknown"] == "OK"
    assert st["HYDRA_BACKUP_DIR"] == "OK"
    assert st["schema_version"] == "OK"


def test_stock_etf_irx_must_share_one_date():
    prices, etf, irx, ranking, state = _frames()
    etf.index = pd.DatetimeIndex(["2026-09-03", "2026-09-03"])
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    last_session="2026-09-04", backup_dir="x")
    assert r["hard"] and _statuses(r)["last bars"] == "HARD"


def test_irx_stale_is_hard():
    prices, etf, irx, ranking, state = _frames()
    irx = irx.iloc[:1]
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    last_session="2026-09-04", backup_dir="x")
    assert r["hard"] and _statuses(r)["last bars"] == "HARD"


def test_last_bar_not_session_is_hard():
    prices, etf, irx, ranking, state = _frames()
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    last_session="2026-09-08", backup_dir="x")  # following Monday
    assert r["hard"]
    assert "stale yfinance" in next(x["detail"] for x in r["rows"] if x["check"] == "last bars")


def test_weekend_asof_uses_friday():
    prices, etf, irx, ranking, state = _frames()
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    asof="2026-09-05", backup_dir="x")  # Saturday
    assert not r["hard"]
    assert r["session"] == "2026-09-04"


def test_labor_day_asof_uses_friday_not_monday():
    """2026-09-07 is Labor Day: last NYSE session is Friday 09-04, not the weekday itself."""
    prices, etf, irx, ranking, state = _frames()
    assert PF.last_weekday_session("2026-09-07") == "2026-09-04"
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    asof="2026-09-07", backup_dir="x")
    assert not r["hard"]
    assert r["session"] == "2026-09-04"


def test_nine_of_ten_etfs_is_hard():
    prices, etf, irx, ranking, state = _frames(drop_etf=["GLD"])
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    last_session="2026-09-04", backup_dir="x")
    assert r["hard"] and _statuses(r)["ETFs present"] == "HARD"
    assert r["etfs_ok"] == 9


def test_etf_nan_on_last_bar_is_hard():
    prices, etf, irx, ranking, state = _frames(etf_nan=["TLT"])
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    last_session="2026-09-04", backup_dir="x")
    assert r["hard"] and "TLT" in next(x["detail"] for x in r["rows"] if x["check"] == "ETFs present")


def test_print_share_below_90_warns():
    prices, etf, irx, ranking, state = _frames(n_stocks=10, missing_last=2)  # 80%
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    last_session="2026-09-04", backup_dir="x")
    assert not r["hard"]
    assert _statuses(r)["universe print share"] == "WARN"
    assert r["print_share"] == pytest.approx(0.8)


def test_sector_unknown_warns():
    prices, etf, irx, ranking, state = _frames()
    ranking["sector"] = "Other"
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    last_session="2026-09-04", backup_dir="x")
    assert not r["hard"]
    assert _statuses(r)["sector-unknown"] == "WARN"


def test_pending_older_than_one_session_warns():
    prices, etf, irx, ranking, state = _frames()
    # two bars after the plan date -> more than one session behind
    # a real state (TASK-384: preflight now replays the ledger; a skeleton without sleeves is HARD)
    import core.portfolio_engine as E
    state = E.new_state(100000.0, "2026-09-01", V9)
    state["last_run_date"] = "2026-09-01"
    state["pending"] = [{"planned": "2026-09-01", "ticker": "T0", "sleeve": "stocks", "tranche": 0,
                         "side": "buy", "dollars": 100.0}]
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    last_session="2026-09-04", backup_dir="x")
    assert not r["hard"]
    assert _statuses(r)["pending age"] == "WARN"


def test_pending_exactly_one_session_ok():
    prices, etf, irx, ranking, state = _frames()
    # prices has 09-03 and 09-04; planned 09-03, today 09-04 = 1 session behind
    state["pending"] = [{"planned": "2026-09-03"}]
    # Need today=09-04 and only one bar after planned. That's 1 session: OK.
    # The warn is sessions > 1, so add an extra bar after planned.
    prices.index = pd.DatetimeIndex(["2026-09-01", "2026-09-04"])
    etf.index = prices.index
    irx.index = prices.index
    r = PF.evaluate(prices, etf, irx, state={"schema_version": 1, "pending": [{"planned": "2026-09-03"}]},
                    ranking=ranking, last_session="2026-09-04", backup_dir="x")
    # bars after 09-03 and <= 09-04: only 09-04 -> 1 session -> OK
    assert _statuses(r)["pending age"] == "OK"


def test_backup_dir_unset_warns(monkeypatch):
    monkeypatch.delenv("HYDRA_BACKUP_DIR", raising=False)
    prices, etf, irx, ranking, state = _frames()
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    last_session="2026-09-04", backup_dir=None)
    assert _statuses(r)["HYDRA_BACKUP_DIR"] == "WARN"


def test_unknown_schema_is_hard():
    prices, etf, irx, ranking, state = _frames()
    state["schema_version"] = 99
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    last_session="2026-09-04", backup_dir="x")
    assert r["hard"] and _statuses(r)["schema_version"] == "HARD"


def test_missing_schema_is_hard():
    prices, etf, irx, ranking, state = _frames()
    state.pop("schema_version")
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    last_session="2026-09-04", backup_dir="x")
    assert r["hard"] and _statuses(r)["schema_version"] == "HARD"


def test_raise_if_hard_stops_unless_force():
    prices, etf, irx, ranking, state = _frames(drop_etf=["GLD"])
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    last_session="2026-09-04", backup_dir="x")
    with pytest.raises(SystemExit, match="preflight hard fail"):
        PF.raise_if_hard(r, force=False)
    PF.raise_if_hard(r, force=True)  # no raise


def test_format_table_lists_status():
    prices, etf, irx, ranking, state = _frames()
    r = PF.evaluate(prices, etf, irx, state=state, ranking=ranking,
                    last_session="2026-09-04", backup_dir="x")
    text = PF.format_table(r)
    assert "[v9] preflight" in text
    assert "OK" in text


def test_run_stops_on_hard_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))

    def bad(_u=None):
        m = _market()
        m["etf"] = m["etf"].drop(columns=["GLD"])
        return m

    with pytest.raises(SystemExit, match="preflight hard fail"):
        V.run(tmp_path, capital=100000.0, fetch_fn=bad, rank_fn=_rank,
              engine=FakeEngine(), silent=True)
    assert not (tmp_path / "portfolio_v9.json").exists()


def test_run_force_continues_on_hard_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))

    def bad(_u=None):
        m = _market()
        m["etf"] = m["etf"].drop(columns=["GLD"])
        return m

    out = V.run(tmp_path, capital=100000.0, fetch_fn=bad, rank_fn=_rank,
                engine=FakeEngine(), silent=True, force=True)
    assert Path(out["state_path"]).exists()
    assert out["orders"]
