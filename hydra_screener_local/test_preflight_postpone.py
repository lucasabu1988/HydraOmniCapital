"""TASK-420 — a HARD preflight postpones pending fills; it does not reject them.

Nothing is written. The gate is unchanged. No network.
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import portfolio_v9 as V  # noqa: E402
from config import V9  # noqa: E402
from data.fetch import attach_observed  # noqa: E402
from test_portfolio_v9_cli import FakeEngine, _market, _rank  # noqa: E402

ETF = list(V9["etf_universe"])
IDX = pd.DatetimeIndex(["2026-09-04", "2026-09-08", "2026-09-10"])


def _hard_market(_universe=None):
    """Stocks print on 2026-09-10; ETFs only observed on 2026-09-08 -> ETF HARD."""
    prices = pd.DataFrame({"AAA": [10.0, 10.5, 11.0]}, index=IDX)
    etf = pd.DataFrame({t: [100.0, 101.0, 101.0] for t in ETF}, index=IDX)
    obs = pd.DataFrame(True, index=IDX, columns=etf.columns)
    obs.iloc[-1] = False
    attach_observed(etf, obs)
    spy = pd.Series([400.0, 401.0, 402.0], index=IDX, name="SPY")
    irx = pd.Series([5.25, 5.20, 5.20], index=IDX)
    names = list(ETF)
    return dict(
        prices=prices, volumes=prices * 1000, spy=spy, etf=etf, irx=irx,
        stock_report={"source": "yfinance", "fetched_at": "2026-09-10T19:36:00Z"},
        etf_report={"source": "yfinance", "fetched_at": "2026-09-10T19:36:00Z",
                    "last_observed": {t: "2026-09-08" for t in names}},
        irx_report={"source": "yfinance", "fetched_at": "2026-09-10T19:36:00Z"},
    )


def test_hard_without_pending_does_not_say_postponing(tmp_path, capsys):
    with pytest.raises(SystemExit, match="preflight hard fail") as ei:
        V.run(tmp_path, capital=100000.0, fetch_fn=_hard_market, rank_fn=_rank,
              engine=FakeEngine(), silent=False)
    assert "POSTPONING" not in str(ei.value)
    assert "POSTPONING" not in capsys.readouterr().out
    assert not (tmp_path / "portfolio_v9.json").exists()


def test_hard_with_pending_postpones_and_writes_nothing(tmp_path, capsys):
    eng = FakeEngine()
    V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=eng, silent=True)
    state_path = tmp_path / "portfolio_v9.json"
    before = state_path.read_text(encoding="utf-8")
    sheets = {p.name: p.read_bytes() for p in tmp_path.glob("instructions_*")}
    assert json.loads(before)["pending"]

    with pytest.raises(SystemExit, match="POSTPONING") as ei:
        V.run(tmp_path, capital=100000.0, fetch_fn=_hard_market, rank_fn=_rank,
              engine=eng, silent=False)
    msg = str(ei.value)
    assert "preflight hard fail" in msg
    assert "POSTPONING 1 pending order(s) planned 2026-09-04" in msg
    assert "exec_date would be 2026-09-08" in msg
    assert "already in the frame" in msg
    out = capsys.readouterr().out
    assert "POSTPONING 1 pending order(s)" in out
    assert state_path.read_text(encoding="utf-8") == before
    assert {p.name: p.read_bytes() for p in tmp_path.glob("instructions_*")} == sheets
    assert eng.settles == 0


def _hard_market_today_is_plan_day(_universe=None):
    """Same ETF HARD, but the price calendar stops on the plan date itself."""
    idx = pd.DatetimeIndex(["2026-09-03", "2026-09-04"])
    prices = pd.DataFrame({"AAA": [10.0, 10.5]}, index=idx)
    etf = pd.DataFrame({t: [100.0, 100.0] for t in ETF}, index=idx)
    obs = pd.DataFrame(True, index=idx, columns=etf.columns)
    obs.iloc[-1] = False
    attach_observed(etf, obs)
    return dict(
        prices=prices, volumes=prices * 1000,
        spy=pd.Series([400.0, 401.0], index=idx, name="SPY"),
        etf=etf, irx=pd.Series([5.25, 5.20], index=idx),
        stock_report={"source": "yfinance", "fetched_at": "2026-09-04T19:36:00Z"},
        etf_report={"source": "yfinance", "fetched_at": "2026-09-04T19:36:00Z",
                    "last_observed": {t: "2026-09-03" for t in ETF}},
        irx_report={"source": "yfinance", "fetched_at": "2026-09-04T19:36:00Z"},
    )


def test_before_t_plus_1_the_hard_does_not_claim_a_postpone(tmp_path, capsys):
    """A HARD on the plan day postpones nothing: the settle block is guarded by today > planned.

    Claiming POSTPONING here would blame the gate for a wait the engine imposes anyway.
    """
    eng = FakeEngine()
    V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=eng, silent=True)
    state = json.loads((tmp_path / "portfolio_v9.json").read_text(encoding="utf-8"))
    assert state["pending"] and state["pending"][0]["planned"] == "2026-09-04"

    with pytest.raises(SystemExit) as ei:
        V.run(tmp_path, capital=100000.0, fetch_fn=_hard_market_today_is_plan_day,
              rank_fn=_rank, engine=eng, silent=False)
    msg = str(ei.value) + capsys.readouterr().out
    assert "POSTPONING" not in msg
    assert "still waiting for t+1" in msg
    assert eng.settles == 0


def test_describing_the_postpone_can_go_quiet_but_never_aborts(tmp_path, capsys, monkeypatch):
    """The description is observability: it may go quiet, it may not replace the gate.

    A malformed `planned` cannot reach here (preflight.evaluate parses it first and would
    raise at line ~349), so the guard is exercised the only honest way: make the describer
    itself fail and assert the run still dies of the gate, with a named AVISO.
    """
    eng = FakeEngine()
    V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=eng, silent=True)
    before = (tmp_path / "portfolio_v9.json").read_text(encoding="utf-8")

    def boom(*_a, **_k):
        raise RuntimeError("describer broke")
    monkeypatch.setattr(V, "pending_postpone_message", boom)

    with pytest.raises(SystemExit, match="preflight hard fail") as ei:
        V.run(tmp_path, capital=100000.0, fetch_fn=_hard_market, rank_fn=_rank,
              engine=eng, silent=False)
    assert "POSTPONING" not in str(ei.value)
    assert "no se pudo describir el aplazamiento" in capsys.readouterr().out
    assert eng.settles == 0
    assert (tmp_path / "portfolio_v9.json").read_text(encoding="utf-8") == before
