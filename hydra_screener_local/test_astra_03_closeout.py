"""ASTRA-03 close-out: WARN severity with a stable id, the refusal moved into the settle,
unresolved obligations, and a sheet that does not value the book at a price nobody printed.

Lucas 2026-09-07 set the severity rule: HARD only for an inconsistency that makes state, cash,
positions, ledger, portfolio identity or the ability to execute and reconcile untrustworthy; WARN for
observed-price differences and information not yet available at that hour. Applying it to the
intraday row does NOT make an intraday fill acceptable — it moves the refusal from the gate that
blocked every run to the one operation that must not happen.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import portfolio_v9 as V
import preflight as PF
from config import V9
from core import portfolio_engine as E

ETF = list(V9["etf_universe"])


# ------------------------------------------------------------------ ids and severity
def _evaluate(state=None, **kw):
    idx = pd.to_datetime(["2026-09-14", "2026-09-15"])
    prices = pd.DataFrame({"AAA": [100.0, 101.0]}, index=idx)
    etf = pd.DataFrame({t: [100.0, 101.0] for t in ETF}, index=idx)
    irx = pd.Series([5.2, 5.2], index=idx)
    return PF.evaluate(prices, etf, irx, state=state, asof="2026-09-15",
                       last_session="2026-09-15", **kw)


def test_every_row_carries_a_stable_id_and_the_set_is_pinned():
    """A rename must fail here rather than silently mint a new id (Lucas: stable identifier)."""
    pf = _evaluate(state=E.new_state(8000.0, "2026-09-04", V9))
    ids = sorted(r["id"] for r in pf["rows"])
    assert ids == ["etfs_present", "hydra_backup_dir", "last_bars", "pending_age",
                   "schema_version", "sector_unknown", "unfilled_orders",
                   "universe_print_share"], ids
    assert all(r["id"] and r["id"] == r["id"].lower() for r in pf["rows"])
    assert PF.row_by_id(pf, "last_bars")["check"] == "last bars"
    assert PF.row_by_id(pf, "nope") is None


def test_the_slug_is_derived_from_the_check_name():
    assert PF._slug("session closed") == "session_closed"
    assert PF._slug("HYDRA_BACKUP_DIR") == "hydra_backup_dir"
    assert PF._slug("sector-unknown") == "sector_unknown"


def test_an_unclosed_session_is_a_warning_not_a_block():
    """The old row was HARD, which stopped daily.py from preparing a cycle before the close."""
    clock = pd.Timestamp("2026-09-15 11:00", tz="America/New_York")
    row = PF._session_closed_row("2026-09-15", clock, allow_intraday=False)
    assert row["status"] == "WARN" and row["id"] == "session_closed"
    assert "the settle refuses it" in row["detail"]
    assert "OVERRIDDEN" not in row["detail"]


def test_the_override_is_written_into_the_row_itself():
    clock = pd.Timestamp("2026-09-15 11:00", tz="America/New_York")
    row = PF._session_closed_row("2026-09-15", clock, allow_intraday=True)
    assert row["status"] == "WARN"
    assert "OVERRIDDEN by --allow-intraday" in row["detail"]


def test_a_closed_session_is_ok():
    clock = pd.Timestamp("2026-09-15 18:00", tz="America/New_York")
    assert PF._session_closed_row("2026-09-15", clock, allow_intraday=False)["status"] == "OK"


# ------------------------------------------------------------------ unresolved obligations
def test_an_unresolved_obligation_is_hard():
    state = E.new_state(8000.0, "2026-09-04", V9)
    state["unfilled"] = [dict(exec_date="2026-09-14", sleeve="stocks", tranche=0, ticker="AAA",
                              side="buy", dollars=1000.0, reason="no price on execution day")]
    row = PF.row_by_id(_evaluate(state=state), "unfilled_orders")
    assert row["status"] == "HARD"
    assert "AAA@2026-09-14" in row["detail"] and "confirm_fills.py" in row["detail"]


def test_no_obligation_is_ok():
    row = PF.row_by_id(_evaluate(state=E.new_state(8000.0, "2026-09-04", V9)), "unfilled_orders")
    assert row["status"] == "OK"


def test_recording_an_obligation_is_idempotent():
    state = E.new_state(8000.0, "2026-09-04", V9)
    fills = [dict(exec_date="2026-09-14", sleeve="stocks", tranche=0, ticker="AAA", side="buy",
                  dollars=1000.0, status="not_filled", reason="no price on execution day"),
             dict(exec_date="2026-09-14", sleeve="etf", tranche=0, ticker="SPY", side="buy",
                  dollars=500.0, status="filled", price=100.0)]
    added = V._record_unfilled(state, fills, "2026-09-15")
    assert len(added) == 1 and added[0]["ticker"] == "AAA"
    assert added[0]["seen"] == "2026-09-15" and added[0]["dollars"] == 1000.0
    assert V._record_unfilled(state, fills, "2026-09-16") == []
    assert len(state["unfilled"]) == 1, "a second run must not duplicate the obligation"


# ------------------------------------------------------------------ through the CLI
def _market(_universe=None):
    """09-11 planned, 09-14 executable, 09-15 the last bar."""
    idx = pd.to_datetime(["2026-09-11", "2026-09-14", "2026-09-15"])
    prices = pd.DataFrame({"AAA": [98.0, 100.0, 99.0]}, index=idx)
    etf = pd.DataFrame({t: [100.0, 100.0, 101.0] for t in ETF}, index=idx)
    return dict(prices=prices, volumes=prices * 1000,
                spy=pd.Series([400.0, 401.0, 402.0], index=idx, name="SPY"),
                etf=etf, irx=pd.Series([5.25, 5.25, 5.20], index=idx),
                stock_report={}, etf_report={}, irx_report={})


def _rank(prices, spy, volumes):
    return pd.DataFrame({"ticker": ["AAA"], "rank": [1], "sector": ["Other"],
                         "recommended": [False], "reason": [""], "recommended_count": [0]})


def _seed_pending(state_dir: Path, planned="2026-09-11", exec_bar_is_last=False) -> Path:
    path = state_dir / V.STATE_NAME
    state = E.new_state(8000.0, "2026-09-04", V9)
    state["last_run_date"] = planned
    state["pending"] = [dict(planned=planned, sleeve="stocks", tranche=0, ticker="AAA",
                             side="buy", dollars=1000.0, cost_bp=0.0)]
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def _pf_with_open_session(monkeypatch, allow=False):
    """Force the intraday WARN through: an injected fetch has no wall clock to ask."""
    real = PF.evaluate

    def fake(*a, **kw):
        pf = real(*a, **kw)
        pf["rows"] = [r for r in pf["rows"] if r["id"] != "session_closed"]
        pf["rows"].append(PF._row("session closed", "WARN",
                                  "last bar is the CURRENT session and it has not closed"
                                  + (" [OVERRIDDEN by --allow-intraday]" if allow else "")))
        pf["warn"] = True
        return pf

    monkeypatch.setattr(V.PF, "evaluate", fake)


def test_run_refuses_to_settle_at_an_unclosed_session_bar(tmp_path, monkeypatch):
    """The 30-order scenario: a run during the session must not book fills at a partial print."""
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))
    _pf_with_open_session(monkeypatch)
    _seed_pending(tmp_path, planned="2026-09-14")   # exec bar = 09-15 = the last, unclosed bar
    out = V.run(tmp_path, fetch_fn=_market, rank_fn=_rank, silent=True, dividend_fn=lambda _t: [])
    assert out["settle_refused"]["reason"] == "session_not_closed"
    assert out["settle_refused"]["exec_date"] == "2026-09-15"
    assert out["fills"] == []
    state = json.loads(Path(out["state_path"]).read_text(encoding="utf-8"))
    assert len(state["pending"]) == 1, "the order must stay pending, not be consumed"
    assert state["ledger"] == []
    assert state["sleeves"]["stocks"]["tranches"][0]["units"] == {}


def test_allow_intraday_settles_and_says_who_authorised_it(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))
    _pf_with_open_session(monkeypatch, allow=True)
    _seed_pending(tmp_path, planned="2026-09-14")
    out = V.run(tmp_path, fetch_fn=_market, rank_fn=_rank, silent=True,
                dividend_fn=lambda _t: [], allow_intraday=True)
    assert out["settle_refused"]["reason"] == "overridden"
    assert "--allow-intraday" in out["settle_refused"]["detail"]
    state = json.loads(Path(out["state_path"]).read_text(encoding="utf-8"))
    assert state["pending"] == [] and len(state["ledger"]) == 1
    assert state["ledger"][0]["price"] == pytest.approx(99.0)


def test_a_closed_session_settles_as_before(tmp_path, monkeypatch):
    """The refusal must not fire on the normal path — this is the Wednesday run."""
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))
    _seed_pending(tmp_path, planned="2026-09-11")   # exec bar = 09-14, not the last bar
    out = V.run(tmp_path, fetch_fn=_market, rank_fn=_rank, silent=True, dividend_fn=lambda _t: [])
    assert out["settle_refused"] is None
    state = json.loads(Path(out["state_path"]).read_text(encoding="utf-8"))
    fill = [f for f in state["ledger"] if f.get("ticker") == "AAA"][0]
    assert fill["exec_date"] == "2026-09-14" and fill["price"] == pytest.approx(100.0)
    assert not state.get("unfilled")


def test_a_gap_on_the_execution_bar_leaves_an_obligation_and_a_hard_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))

    def gapped(_universe=None):
        m = _market()
        m["prices"] = m["prices"].copy()
        m["prices"].loc[pd.Timestamp("2026-09-14"), "AAA"] = np.nan
        m["volumes"] = m["prices"] * 1000
        return m

    _seed_pending(tmp_path, planned="2026-09-11")
    out = V.run(tmp_path, fetch_fn=gapped, rank_fn=_rank, silent=True, dividend_fn=lambda _t: [])
    state = json.loads(Path(out["state_path"]).read_text(encoding="utf-8"))
    assert [f["status"] for f in state["ledger"]] == ["not_filled"]
    assert len(state["unfilled"]) == 1
    rec = state["unfilled"][0]
    assert (rec["ticker"], rec["exec_date"], rec["side"]) == ("AAA", "2026-09-14", "buy")
    assert rec["reason"] == "no price on execution day"
    # the cash is still there and the position never opened: the next run must refuse to plan
    assert state["sleeves"]["stocks"]["tranches"][0]["units"] == {}
    row = PF.row_by_id(_evaluate(state=state), "unfilled_orders")
    assert row["status"] == "HARD"


def test_the_obligation_is_not_re_issued(tmp_path, monkeypatch):
    """Re-planning it while the broker did fill would buy the name twice."""
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))
    state = E.new_state(8000.0, "2026-09-04", V9)
    state["unfilled"] = [dict(exec_date="2026-09-14", sleeve="stocks", tranche=0, ticker="AAA",
                              side="buy", dollars=1000.0, reason="no price on execution day")]
    (tmp_path / V.STATE_NAME).write_text(json.dumps(state), encoding="utf-8")
    out = V.run(tmp_path, fetch_fn=_market, rank_fn=_rank, silent=True,
                dividend_fn=lambda _t: [], force=True)
    assert not any(o.get("ticker") == "AAA" and o.get("side") == "buy"
                   for o in (out["orders"] or []) if o.get("reissued"))
    after = json.loads(Path(out["state_path"]).read_text(encoding="utf-8"))
    assert len(after["unfilled"]) == 1, "the obligation survives until confirm_fills.py resolves it"


# ------------------------------------------------------------------ the sheet's valuation
def test_the_sheet_names_the_bar_it_valued_and_the_names_it_carried(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))

    def held_but_dark(_universe=None):
        """AAA is held and stops printing on the last bar; the ETF sleeve keeps printing."""
        m = _market()
        m["prices"] = m["prices"].copy()
        m["prices"].loc[pd.Timestamp("2026-09-15"), "AAA"] = np.nan
        m["volumes"] = m["prices"] * 1000
        return m

    state = E.new_state(8000.0, "2026-09-04", V9)
    state["last_run_date"] = "2026-09-14"
    tr = state["sleeves"]["stocks"]["tranches"][0]
    tr["units"], tr["last_px"], tr["cash"] = {"AAA": 10.0}, {"AAA": 100.0}, 0.0
    state["ledger"] = [dict(exec_date="2026-09-14", sleeve="stocks", tranche=0, ticker="AAA",
                            side="buy", units=10.0, price=100.0, dollars=1000.0, cost=0.0,
                            status="filled")]
    (tmp_path / V.STATE_NAME).write_text(json.dumps(state), encoding="utf-8")

    out = V.run(tmp_path, fetch_fn=held_but_dark, rank_fn=_rank, silent=True,
                dividend_fn=lambda _t: [], force=True)
    assert out["summary"]["as_of"] == "2026-09-15"
    assert out["summary"]["carried_stale"] == ["AAA"]
    sheet = Path(out["instructions_md"]).read_text(encoding="utf-8")
    assert "## Valuation (closes that printed on 2026-09-15)" in sheet
    assert "Carried at their last known price, no print on 2026-09-15: **AAA**" in sheet
    # AAA is carried at last_px 100, not at the 99 an ffill would have shown. The sleeve is
    # 10 units + the 3000 of cash the other three tranches still hold, plus accrued interest;
    # valued at 99 it would come out ~10 lower.
    assert out["summary"]["sleeves"]["stocks"]["value"] == pytest.approx(4000.0, abs=1.0)


def test_a_fully_printing_book_reports_no_carried_names(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))
    _seed_pending(tmp_path, planned="2026-09-11")
    out = V.run(tmp_path, fetch_fn=_market, rank_fn=_rank, silent=True, dividend_fn=lambda _t: [])
    assert out["summary"]["carried_stale"] == []
    assert "Carried at their last known price" not in Path(out["instructions_md"]).read_text(encoding="utf-8")


# ------------------------------------------------------------------ the way out of the HARD gate
def _state_with_obligation():
    state = E.new_state(8000.0, "2026-09-04", V9)
    state["last_run_date"] = "2026-09-14"
    state["ledger"] = [dict(exec_date="2026-09-14", sleeve="stocks", tranche=0, ticker="AAA",
                            side="buy", dollars=1000.0, status="not_filled",
                            reason="no price on execution day")]
    state["unfilled"] = [dict(exec_date="2026-09-14", sleeve="stocks", tranche=0, ticker="AAA",
                              side="buy", dollars=1000.0, reason="no price on execution day")]
    return state


def test_confirming_the_real_fill_clears_the_obligation():
    """A HARD gate with no way out is a gate nobody can satisfy — this is the way out."""
    from core.fills import apply_confirmations
    state = _state_with_obligation()
    res = apply_confirmations(state, [dict(exec_date="2026-09-14", sleeve="stocks", tranche="0",
                                           ticker="AAA", side="buy", units="10", price="100",
                                           fee="0")])
    assert [u["ticker"] for u in res["resolved_unfilled"]] == ["AAA"]
    assert res["state"]["unfilled"] == []
    assert PF.row_by_id(_evaluate(state=res["state"]), "unfilled_orders")["status"] == "OK"


def test_confirming_zero_units_records_that_it_never_filled_and_clears_it():
    """The operator is the only one who knows the broker did nothing; units=0 says so."""
    from core.fills import apply_confirmations
    state = _state_with_obligation()
    res = apply_confirmations(state, [dict(exec_date="2026-09-14", sleeve="stocks", tranche="0",
                                           ticker="AAA", side="buy", units="0", price="0",
                                           fee="0")])
    assert res["state"]["unfilled"] == []
    assert res["state"]["sleeves"]["stocks"]["tranches"][0]["units"] == {}


def test_an_unrelated_confirmation_leaves_the_obligation_standing():
    from core.fills import apply_confirmations
    state = _state_with_obligation()
    res = apply_confirmations(state, [dict(exec_date="2026-09-14", sleeve="etf", tranche="0",
                                           ticker="SPY", side="buy", units="5", price="100",
                                           fee="0")])
    assert res["resolved_unfilled"] == []
    assert len(res["state"]["unfilled"]) == 1
    assert PF.row_by_id(_evaluate(state=res["state"]), "unfilled_orders")["status"] == "HARD"


def test_the_report_names_what_it_resolved():
    from core.fills import apply_confirmations, report_lines
    state = _state_with_obligation()
    res = apply_confirmations(state, [dict(exec_date="2026-09-14", sleeve="stocks", tranche="0",
                                           ticker="AAA", side="buy", units="10", price="100",
                                           fee="0")])
    text = "\n".join(report_lines(res))
    assert "RESOLVED unfilled AAA@2026-09-14" in text


def test_the_journal_records_the_refusal_itself(tmp_path, monkeypatch):
    """Inferable is not recorded: the reason 30 orders were not settled has to be in the record."""
    import journal as J
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))
    _pf_with_open_session(monkeypatch)
    _seed_pending(tmp_path, planned="2026-09-14")
    out = V.run(tmp_path, fetch_fn=_market, rank_fn=_rank, silent=True, dividend_fn=lambda _t: [])
    path = J.append_from_v9(out, journal_dir=tmp_path / "journal", oos_step_returns=[])
    rec = json.loads(Path(path).read_text(encoding="utf-8"))
    refused = rec["process"]["settle_refused"]
    assert refused["reason"] == "session_not_closed" and refused["exec_date"] == "2026-09-15"
    assert refused["orders"] == 1
    # and the WARN that explains it travels with its stable id
    ids = [r.get("id") for r in rec["process"]["preflight"]["rows"]]
    assert "session_closed" in ids


def test_an_ordinary_run_records_no_refusal(tmp_path, monkeypatch):
    import journal as J
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))
    _seed_pending(tmp_path, planned="2026-09-11")
    out = V.run(tmp_path, fetch_fn=_market, rank_fn=_rank, silent=True, dividend_fn=lambda _t: [])
    path = J.append_from_v9(out, journal_dir=tmp_path / "journal", oos_step_returns=[])
    assert json.loads(Path(path).read_text(encoding="utf-8"))["process"]["settle_refused"] is None
