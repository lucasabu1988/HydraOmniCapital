"""TASK-416 — a degraded provider refresh has a name.

The HARD gate is unchanged. These tests never hit the network.
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from config import PROVIDER_REFRESH_DEGRADE_SHARE  # noqa: E402
from data.fetch import (  # noqa: E402
    attach_observed,
    attach_print_quality,
    degraded_groups,
    format_provider_degraded,
    frame_print_quality,
    load_last_ok_print_quality,
    save_last_ok_print_quality,
)


def _frame(n_printed: int, n: int = 10, last="2026-09-10"):
    idx = pd.DatetimeIndex(["2026-09-09", last])
    px = pd.DataFrame({f"T{i}": [10.0, 10.0] for i in range(n)}, index=idx)
    obs = pd.DataFrame(True, index=idx, columns=px.columns)
    obs.iloc[-1, n_printed:] = False
    attach_observed(px, obs)
    return px


def test_frame_print_quality_uses_the_observed_mask_not_the_ffill():
    px = _frame(1, n=10)
    px.iloc[-1] = 10.0                         # ffill would make every cell look printed
    rec = frame_print_quality(px)
    assert rec["n"] == 10 and rec["n_printed"] == 1
    assert rec["print_share"] == pytest.approx(0.1)
    assert rec["last_bar"] == "2026-09-10"


def test_degraded_when_share_drops_more_than_the_declared_threshold():
    now = {"etf": {"print_share": 0.07, "last_bar": "2026-09-09"}}
    prev = {"at": "2026-09-10T16:55:00Z",
            "groups": {"etf": {"print_share": 1.0, "last_bar": "2026-09-10"}}}
    hits = degraded_groups(now, prev)
    assert len(hits) == 1 and hits[0]["group"] == "etf"
    assert hits[0]["drop"] == pytest.approx(0.93)
    msg = format_provider_degraded(hits)
    assert msg.startswith("provider refresh degraded:")
    assert "etf print_share 7%" in msg and "last ok 100%" in msg
    assert "retry later" in msg


def test_small_drop_is_not_named_degraded():
    now = {"etf": {"print_share": 0.95, "last_bar": "2026-09-10"}}
    prev = {"groups": {"etf": {"print_share": 1.0, "last_bar": "2026-09-10"}}}
    assert PROVIDER_REFRESH_DEGRADE_SHARE == 0.20
    assert degraded_groups(now, prev) == []
    assert format_provider_degraded([]) is None


def test_no_previous_run_is_not_degraded():
    now = {"stocks": {"print_share": 0.07, "last_bar": "2026-09-09"}}
    assert degraded_groups(now, None) == []


def test_last_ok_sidecar_round_trip_same_universe(tmp_path):
    groups = {"etf": attach_print_quality(_frame(10, 10), "etf")}
    save_last_ok_print_quality(groups, universe="all", runs_dir=tmp_path, at="2026-09-10T16:55:00Z")
    rec = load_last_ok_print_quality(runs_dir=tmp_path, universe="all")
    assert rec["universe"] == "all" and rec["at"] == "2026-09-10T16:55:00Z"
    assert rec["groups"]["etf"]["print_share"] == pytest.approx(1.0)
    assert load_last_ok_print_quality(runs_dir=tmp_path, universe="sp500") is None


def test_v9_prints_the_name_and_still_hards_never_saves_last_ok(tmp_path, capsys, monkeypatch):
    import portfolio_v9 as V
    from config import V9
    from test_portfolio_v9_cli import FakeEngine, _rank

    prev = {"at": "2026-09-10T16:55:00Z", "universe": "all",
            "groups": {"etf": {"print_share": 1.0, "last_bar": "2026-09-10"}}}
    monkeypatch.setattr(V, "load_last_ok_print_quality", lambda universe=None: prev)
    saved = []
    monkeypatch.setattr(V, "save_last_ok_print_quality", lambda *a, **k: saved.append(1))
    idx = pd.DatetimeIndex(["2026-09-09", "2026-09-10"])

    def market(_u=None):
        prices = pd.DataFrame({"AAA": [10.0, 10.0]}, index=idx)
        etf = pd.DataFrame({t: [100.0, 100.0] for t in V9["etf_universe"]}, index=idx)
        obs = pd.DataFrame(False, index=idx, columns=etf.columns)
        obs.iloc[0] = True
        attach_observed(etf, obs)
        names = list(V9["etf_universe"])
        return dict(
            prices=prices, volumes=prices * 1000,
            spy=pd.Series([400.0, 401.0], index=idx, name="SPY"),
            etf=etf, irx=pd.Series([5.25, 5.25], index=idx),
            stock_report={"source": "yfinance", "fetched_at": "2026-09-10T19:36:00Z"},
            etf_report={"source": "yfinance", "fetched_at": "2026-09-10T19:36:00Z",
                        "last_observed": {t: "2026-09-09" for t in names}},
            irx_report={"source": "yfinance", "fetched_at": "2026-09-10T19:36:00Z"},
        )

    with pytest.raises(SystemExit):
        V.run(tmp_path, capital=100000.0, fetch_fn=market, rank_fn=_rank,
              engine=FakeEngine(), silent=False)
    out = capsys.readouterr().out
    assert "provider refresh degraded" in out
    assert saved == [], "a HARD run must not become the last successful refresh"


# --- Claude's review of TASK-416: the diagnostic must never abort a run -------------------
# Both calls sit on the live path between the preflight table and the settle. A corrupt
# sidecar or a read-only runs/ costs the diagnostic, never the fills.

def test_diagnostic_survives_a_broken_sidecar_and_returns_nothing(capsys, monkeypatch):
    import portfolio_v9 as V

    def boom(*a, **k):
        raise OSError("runs/ is not readable")

    monkeypatch.setattr(V, "load_last_ok_print_quality", boom)
    groups, msg = V._print_quality_diagnostic(_frame(10, 10), _frame(10, 10), None, "all", silent=False)
    assert (groups, msg) == (None, None)
    assert "no se pudo medir la calidad del refresco" in capsys.readouterr().out


def test_diagnostic_is_silent_about_its_own_failure_when_silent(capsys, monkeypatch):
    import portfolio_v9 as V
    monkeypatch.setattr(V, "groups_print_quality", lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
    assert V._print_quality_diagnostic(None, None, None, "all", silent=True) == (None, None)
    assert capsys.readouterr().out == ""


def test_save_failure_does_not_propagate_and_says_so(capsys, monkeypatch):
    import portfolio_v9 as V

    def boom(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(V, "save_last_ok_print_quality", boom)
    assert V._save_print_quality({"etf": {"print_share": 1.0}}, "all", silent=False) is False
    assert "no se pudo guardar last_ok_print_quality" in capsys.readouterr().out


def test_save_is_skipped_when_the_diagnostic_produced_nothing(monkeypatch):
    import portfolio_v9 as V
    calls = []
    monkeypatch.setattr(V, "save_last_ok_print_quality", lambda *a, **k: calls.append(1))
    assert V._save_print_quality(None, "all", silent=True) is False
    assert calls == [], "nothing measured must not overwrite the last successful refresh"


def test_a_good_run_still_records_itself(monkeypatch):
    import portfolio_v9 as V
    seen = {}
    monkeypatch.setattr(V, "save_last_ok_print_quality",
                        lambda groups, universe=None: seen.update(groups=groups, universe=universe))
    assert V._save_print_quality({"etf": {"print_share": 1.0}}, "all", silent=True) is True
    assert seen["universe"] == "all" and seen["groups"]["etf"]["print_share"] == 1.0
