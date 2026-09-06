"""Audit phase 9 — append-only journal, universe propagation, operational alerts.

Reproductions R-901..R-905 in docs/AUDIT_REPRODUCTIONS.md. No network.
"""
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core.alerts as A  # noqa: E402
import journal as J  # noqa: E402
import portfolio_v9 as V  # noqa: E402
from config import UNIVERSE, V9  # noqa: E402

N = 301
STOCKS = ("AAA", "BBB", "CCC")


def _fetch(_universe=None):
    idx = pd.bdate_range("2025-01-01", periods=N)
    stocks = pd.DataFrame({t: np.linspace(10.0, 20.0, N) for t in STOCKS}, index=idx)
    etf = pd.DataFrame({t: np.linspace(50.0, 60.0, N) for t in V9["etf_universe"]}, index=idx)
    return dict(prices=stocks, volumes=stocks * 1e6,
                spy=pd.Series(np.linspace(400.0, 500.0, N), index=idx),
                etf=etf, irx=pd.Series(4.0, index=idx),
                stock_report={}, etf_report={}, irx_report={},
                universe_requested="(unset)", universe_effective="all",
                universe_tickers=list(STOCKS))


def _rank(prices, spy, volumes, universe=None):
    return pd.DataFrame({"ticker": list(STOCKS), "rank": [1, 2, 3], "sector": ["Tech"] * 3,
                         "recommended": [True] * 3, "reason": [""] * 3,
                         "composite": [1.0, 0.9, 0.8]})


def _record(date="2026-09-04", total=100000.0, n_orders=13):
    return {"date": date, "book": {"total": total}, "did": {"n_orders": n_orders},
            "seen": {}, "process": {"errors": []}}


# ------------------------------------------------------------------ R-901
def test_r901_a_rerun_the_same_day_creates_a_revision(tmp_path):
    """R-901 — phase 9.5. `<date>.json` was rewritten in place, so the evidence of
    what the earlier run of that day recommended was gone."""
    J.save_record(_record(n_orders=13), tmp_path)
    J.save_record(_record(n_orders=0), tmp_path)

    revs = J.load_revisions(tmp_path, "2026-09-04")
    assert [r["revision"] for r in revs] == [1, 2]
    assert revs[0]["did"]["n_orders"] == 13, "the first run's evidence survives"
    assert revs[1]["did"]["n_orders"] == 0
    assert revs[1]["parent_run_id"] == revs[0]["run_id"]
    assert {p.name for p in tmp_path.glob("2026-09-04_r*.json")} == \
        {"2026-09-04_r01.json", "2026-09-04_r02.json"}


def test_r901_revisions_are_write_once(tmp_path):
    J.save_record(_record(n_orders=13), tmp_path)
    rev = tmp_path / "2026-09-04_r01.json"
    before = rev.read_bytes()
    J.save_record(_record(n_orders=0), tmp_path)
    assert rev.read_bytes() == before


def test_r901_load_records_still_gives_one_row_per_day(tmp_path):
    """The equity curve and prior_total must not double-count a rerun."""
    J.save_record(_record(date="2026-09-04", total=100.0), tmp_path)
    J.save_record(_record(date="2026-09-04", total=110.0), tmp_path)
    J.save_record(_record(date="2026-09-11", total=120.0), tmp_path)
    recs = J.load_records(tmp_path)
    assert [r["date"] for r in recs] == ["2026-09-04", "2026-09-11"]
    assert recs[0]["book"]["total"] == pytest.approx(110.0), "the newest revision wins"
    assert J.prior_total(tmp_path, "2026-09-11") == pytest.approx(110.0)


def test_the_pointer_carries_the_revision_index(tmp_path):
    J.save_record(_record(n_orders=13), tmp_path)
    J.save_record(_record(n_orders=7), tmp_path)
    pointer = json.loads((tmp_path / "2026-09-04.json").read_text(encoding="utf-8"))
    assert [r["revision"] for r in pointer["revisions"]] == [1, 2]
    assert all(r["status"] == "ok" for r in pointer["revisions"])


# ------------------------------------------------------------------ R-902
def test_r902_an_error_does_not_delete_the_successful_record(tmp_path):
    """R-902 — phase 9.4, the worst of this phase. `append_error` went through the
    same in-place write, so a failed run replaced the good record: a book total of
    123,456 became 0.0."""
    J.save_record(_record(total=123456.0), tmp_path)
    J.append_error("yfinance timeout", journal_dir=tmp_path, today="2026-09-04")

    pointer = json.loads((tmp_path / "2026-09-04.json").read_text(encoding="utf-8"))
    assert pointer["book"]["total"] == pytest.approx(123456.0), "the good record survives"
    assert pointer["status"] == "ok"
    assert pointer["last_failure"]["error"] == ["yfinance timeout"]

    revs = J.load_revisions(tmp_path, "2026-09-04")
    assert [r["status"] for r in revs] == ["ok", "failed"]
    assert revs[1]["error"] == ["yfinance timeout"]


def test_r902_a_day_that_only_failed_is_still_visible(tmp_path):
    J.append_error("provider down", journal_dir=tmp_path, today="2026-09-04")
    pointer = json.loads((tmp_path / "2026-09-04.json").read_text(encoding="utf-8"))
    assert pointer["status"] == "failed"
    assert pointer["error"] == ["provider down"]
    assert J.latest_successful(tmp_path, "2026-09-04") is None


def test_r902_a_success_after_a_failure_takes_the_pointer_back(tmp_path):
    J.append_error("provider down", journal_dir=tmp_path, today="2026-09-04")
    J.save_record(_record(total=99.0), tmp_path)
    pointer = json.loads((tmp_path / "2026-09-04.json").read_text(encoding="utf-8"))
    assert pointer["status"] == "ok"
    assert pointer["book"]["total"] == pytest.approx(99.0)
    assert [r["status"] for r in J.load_revisions(tmp_path, "2026-09-04")] == ["failed", "ok"]


def test_r902_the_equity_curve_does_not_regress_on_an_error(tmp_path):
    J.save_record(_record(date="2026-09-04", total=100000.0), tmp_path)
    J.append_error("boom", journal_dir=tmp_path, today="2026-09-11")
    assert J.prior_total(tmp_path, "2026-09-18") == pytest.approx(100000.0)


def test_observations_still_merge_across_revisions(tmp_path):
    J.save_record(_record(), tmp_path, note="first note")
    J.save_record(_record(), tmp_path, note="second note")
    pointer = json.loads((tmp_path / "2026-09-04.json").read_text(encoding="utf-8"))
    assert pointer["observations"] == ["first note", "second note"]


# ------------------------------------------------------------------ R-903
def test_r903_every_record_carries_the_required_fields(tmp_path):
    """R-903 — phase 9.3: run_id, revision, parent_run_id, status, error, inputs,
    outputs, timestamps. None of them existed."""
    J.save_record(_record(), tmp_path)
    rec = J.load_revisions(tmp_path, "2026-09-04")[0]
    for field in ("run_id", "revision", "parent_run_id", "status", "error",
                  "inputs", "outputs", "created_at"):
        assert field in rec, field
    assert rec["revision"] == 1
    assert rec["parent_run_id"] is None
    assert rec["status"] == "ok"
    assert rec["created_at"].endswith("Z")


def test_r903_append_from_v9_records_inputs_and_outputs(tmp_path):
    out = V.run(tmp_path / "state", capital=100000.0, fetch_fn=_fetch, rank_fn=_rank,
                silent=True)
    J.append_from_v9(out, journal_dir=tmp_path / "journal")
    rec = J.load_revisions(tmp_path / "journal", out["today"])[0]
    assert rec["run_id"] == out["run_id"]
    assert rec["inputs"]["universe_effective"] == "all"
    assert rec["inputs"]["last_bars"]["stocks"] == out["today"]
    assert rec["outputs"]["run_status"] == "committed"
    assert rec["outputs"]["n_orders"] == len(out["orders"])
    assert rec["outputs"]["instructions_md"] == out["instructions_md"]


# ------------------------------------------------------------------ R-904 universe
def test_r904_the_effective_universe_is_resolved_once_and_recorded():
    """R-904 — phase 9.1/9.2: each stage re-derived the universe from the
    environment and nothing recorded which one actually ran."""
    assert V.resolve_universe("sp500") == ("sp500", "sp500")
    assert V.resolve_universe(None) == ("(unset)", UNIVERSE)


def test_r904_an_explicit_universe_beats_the_environment(monkeypatch):
    monkeypatch.setenv("UNIVERSE", "nasdaq100")
    assert V.resolve_universe("sp500") == ("sp500", "sp500")
    assert V.resolve_universe(None) == ("(unset)", "nasdaq100")


def test_r904_the_run_returns_and_journals_the_effective_universe(tmp_path):
    out = V.run(tmp_path, capital=100000.0, fetch_fn=_fetch, rank_fn=_rank, silent=True)
    assert out["universe_effective"] == "all"
    assert out["universe_requested"] == "(unset)"
    rep = out["universe_report"]
    assert rep["key"] == "all"
    assert rep["is_proxy"] is True, "the production universe is a proxy and says so"
    assert rep["sha256"]
    assert rep["n"] == 3


def test_r904_the_ranking_stage_receives_the_universe():
    seen = {}

    def rank_fn(prices, spy, volumes, universe=None):
        seen["universe"] = universe
        return _rank(prices, spy, volumes)

    out = V._rank(rank_fn, pd.DataFrame({"A": [1.0]}), pd.Series([1.0]),
                  pd.DataFrame({"A": [1.0]}), "sp500")
    assert seen["universe"] == "sp500"
    assert out is not None


def test_r904_a_three_argument_test_double_still_works():
    def old_style(prices, spy, volumes):
        return "ranked"

    assert V._rank(old_style, None, None, None, "sp500") == "ranked"


# ------------------------------------------------------------------ R-905 alerts
def test_r905_no_alerts_on_a_clean_run():
    """R-905 — phase 9.8: nothing surfaced stale data, a missing sheet, unreconciled
    cash or a partial execution as an operational alert."""
    out = {"run_status": "committed", "run_id": "x", "today": "2026-09-04",
           "preflight": {"rows": [{"check": "last bars", "status": "OK", "detail": "ok"}],
                         "price_quality": {"etf": {}}},
           "state": {"pending": []}}
    assert A.collect(out, instructions_exists=True) == []
    assert A.has_errors([]) is False
    assert A.worst_level([]) is None


def test_r905_a_stale_etf_price_is_an_error():
    out = {"run_status": "committed", "today": "2026-09-04",
           "preflight": {"rows": [], "price_quality": {"etf": {
               "SPY": {"status": "observed"}, "IWM": {"status": "stale"}}}},
           "state": {}}
    alerts = A.collect(out)
    codes = [a.code for a in alerts]
    assert "stale_prices" in codes
    assert A.has_errors(alerts) is True
    assert A.worst_level(alerts) == A.ERROR


def test_r905_a_missing_sheet_is_an_error():
    out = {"run_status": "committed", "instructions_md": "state/instructions_20260904.md",
           "preflight": {"rows": []}, "state": {}}
    alerts = A.collect(out, instructions_exists=False)
    assert "sheet_missing" in [a.code for a in alerts]


def test_r905_unreconciled_cash_is_an_error():
    out = {"run_status": "committed", "preflight": {"rows": []}, "state": {},
           "reconcile": {"residual": -42.5}}
    alerts = A.collect(out)
    assert "cash_unreconciled" in [a.code for a in alerts]
    assert any("42.50" in a.message for a in alerts)

    small = A.collect({"run_status": "committed", "preflight": {"rows": []},
                       "state": {}, "reconcile": {"residual": 0.01}})
    assert "cash_unreconciled" not in [a.code for a in small]


def test_r905_a_partial_execution_is_flagged():
    out = {"run_status": "committed", "today": "2026-09-11", "preflight": {"rows": []},
           "state": {"pending": [{"planned": "2026-09-04", "ticker": "AAA"}]}}
    alerts = A.collect(out)
    assert "awaiting_confirmation" in [a.code for a in alerts]


def test_r905_a_run_needing_recovery_is_an_error():
    out = {"run_status": "failed_pending_recovery", "run_id": "r1",
           "preflight": {"rows": []}, "state": {}}
    alerts = A.collect(out)
    assert "recovery_required" in [a.code for a in alerts]
    assert A.has_errors(alerts)

    staged = A.collect({"run_status": "committed", "preflight": {"rows": []}, "state": {}},
                       pending_runs=[{"run_id": "r2", "needs_recovery": True}])
    assert "recovery_required" in [a.code for a in staged]


def test_r905_unverified_dividends_and_refused_orders_are_flagged():
    out = {
        "run_status": "committed", "today": "2026-09-04", "preflight": {"rows": []},
        "dividend_report": {"verified": False, "coverage_through": "2026-08-28",
                            "open_gaps": 2,
                            "conflicts": [{"ticker": "AAA", "ex_date": "2026-09-02",
                                           "values": [0.5, 0.7]}],
                            "rejected": [{"reason": "dps is not finite: nan"}]},
        "state": {"data_errors": [{"date": "2026-09-04", "ticker": "ZZZ"}]},
    }
    codes = [a.code for a in A.collect(out)]
    assert "dividends_unverified" in codes
    assert "dividend_conflict" in codes
    assert "dividend_rejected" in codes
    assert "orders_refused" in codes


def test_r905_a_hard_preflight_row_is_an_error_and_a_warn_row_is_a_warning():
    out = {"run_status": "committed", "state": {}, "preflight": {"rows": [
        {"check": "prices are valid", "status": "HARD", "detail": "close <= 0"},
        {"check": "provenance", "status": "WARN", "detail": "no reports"},
        {"check": "schema_version", "status": "OK", "detail": "1"},
    ]}}
    alerts = A.collect(out)
    levels = {a.code: a.level for a in alerts}
    assert levels["preflight_hard"] == A.ERROR
    assert levels["preflight_warn"] == A.WARN
    assert len(alerts) == 2


def test_r905_alerts_are_sorted_most_serious_first_and_format_readably():
    out = {"run_status": "committed", "state": {}, "preflight": {"rows": [
        {"check": "provenance", "status": "WARN", "detail": "no reports"},
        {"check": "prices are valid", "status": "HARD", "detail": "close <= 0"},
    ]}}
    alerts = A.collect(out)
    assert alerts[0].level == A.ERROR
    text = A.format_alerts(alerts)
    assert "1 error" in text
    assert "preflight_hard" in text
    assert A.format_alerts([]) == "alerts: none"


def test_alert_dicts_are_serialisable():
    out = {"run_status": "failed_pending_recovery", "preflight": {"rows": []}, "state": {}}
    payload = [a.as_dict() for a in A.collect(out)]
    assert json.loads(json.dumps(payload))[0]["level"] == A.ERROR
