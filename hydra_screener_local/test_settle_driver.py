"""The settle driver: the guard that refuses, the netting, and the artefact explainer.

Every case here came out of rehearsing the real settle against a copy of the live book on
2026-09-08. Auto-discovered by run_all_tests.py (pytest-routed: no __main__ block).
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import settle as S  # noqa: E402

RECONCILE_OUT = """[v9] reconcile (read-only, writes nothing)
last_run 2026-09-08

positions  (broker - state)
ticker   kind                  state       broker         diff    last_px
AES      match               21.0000      21.0000       0.0000    14.7944

match 26  missing(state-only) 0  unknown(broker-only) 0  quantity-diff 0

cash
  state  88,773.95  {'stocks': 44259.69, 'etf': 44514.26}
  broker 88,761.19  mode=total
  delta  -12.76  (broker - state)

known explanations (context; interest/dividends/fees already sit in state cash)
  interest recorded   12.7544
  dividends recorded  0.0000
  fees recorded       9.1000
  pending buys        0.0000
  pending sells       0.0000
  Broker pays on pay-date; the book credits ex-date (TASK-349).

unexplained residual  -12.7569  (-0.013% of state equity)
equity at state last_px  state 100,003.65  broker 99,990.90
"""


def _state(tmp_path, *, pending=0, ledger_dates=(), interest=0.0, filled_tickers=()):
    """A state file shaped like the real one, in a temp dir the driver is pointed at."""
    ledger = []
    for d in ledger_dates:
        for tk in (filled_tickers or ("AES",)):
            ledger.append({"exec_date": d, "sleeve": "stocks", "tranche": 0, "ticker": tk,
                           "side": "buy", "status": "filled", "units": 10.0, "price": 10.0,
                           "dollars": 100.0, "cost": 0.1})
    st = {
        "last_run_date": "2026-09-08",
        "pending": [{"sleeve": "stocks", "tranche": 0, "ticker": "ZZZ", "side": "buy",
                     "dollars": 100.0, "est_price": 10.0}] * pending,
        "ledger": ledger,
        "interest": ([{"date": "2026-09-08", "sleeve": "stocks", "dollars": interest}]
                     if interest else []),
        "sleeves": {"stocks": {"tranches": [{"cash": 1000.0, "units": {}, "last_px": {}}]},
                    "etf": {"tranches": [{"cash": 1000.0, "units": {}, "last_px": {}}]}},
        "capital_reference": 2000.0, "transfers": [], "write_offs": [],
    }
    d = tmp_path / "state"
    d.mkdir(parents=True, exist_ok=True)
    (d / "portfolio_v9.json").write_text(json.dumps(st), encoding="utf-8")
    S.use_state_dir(str(d))
    return d


def _csv(tmp_path, rows, name="fills.csv"):
    header = "exec_date,sleeve,tranche,ticker,side,units,price,fee\n"
    body = "".join(f"{r['exec_date']},{r.get('sleeve','stocks')},{r.get('tranche',0)},"
                   f"{r['ticker']},{r.get('side','buy')},{r.get('units',10)},"
                   f"{r.get('price',10.0)},{r.get('fee',0.1)}\n" for r in rows)
    p = tmp_path / name
    p.write_text(header + body, encoding="utf-8")
    return str(p)


# ------------------------------------------------------------------ the guard that matters most
def test_confirming_before_daily_is_refused_with_the_reason():
    """The rehearsal's finding: with an empty ledger every row books as confirmed_unplanned, is
    applied to the tranches anyway, and the pending settle AGAIN next run. Double position."""
    import tempfile
    import pathlib
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        _state(tmp, pending=30, ledger_dates=())
        got = S.order_guard(_csv(tmp, [{"exec_date": "2026-09-08", "ticker": "AES"}]))
    assert got["ok"] is False
    assert "daily.py" in got["reason"]
    assert "double position" in got["reason"].lower()


def test_it_passes_once_the_ledger_has_that_date(tmp_path):
    _state(tmp_path, pending=0, ledger_dates=("2026-09-08",))
    got = S.order_guard(_csv(tmp_path, [{"exec_date": "2026-09-08", "ticker": "AES"}]))
    assert got["ok"] is True
    assert got["ledger_dates"] == ["2026-09-08"]


def test_a_presumed_fill_with_no_csv_row_is_flagged(tmp_path):
    """SNDK / LITE / QQQ: too small to buy one whole share, so no fill row - and the book keeps
    the presumed position unless a units=0 row arrives."""
    _state(tmp_path, ledger_dates=("2026-09-08",), filled_tickers=("AES", "SNDK", "LITE"))
    got = S.order_guard(_csv(tmp_path, [{"exec_date": "2026-09-08", "ticker": "AES"}]))
    assert got["ok"] is True
    assert set(got["presumed_without_a_csv_row"]) == {"SNDK", "LITE"}
    assert "units=0" in got["reason"]


def test_no_warning_when_every_presumed_fill_has_a_row(tmp_path):
    _state(tmp_path, ledger_dates=("2026-09-08",), filled_tickers=("AES", "SNDK"))
    got = S.order_guard(_csv(tmp_path, [{"exec_date": "2026-09-08", "ticker": "AES"},
                                        {"exec_date": "2026-09-08", "ticker": "SNDK",
                                         "units": 0}]))
    assert got["presumed_without_a_csv_row"] == []
    assert "WARNING" not in got["reason"]


def test_an_empty_or_missing_csv_is_refused(tmp_path):
    _state(tmp_path, ledger_dates=("2026-09-08",))
    assert S.order_guard(_csv(tmp_path, []))["ok"] is False
    assert S.order_guard(str(tmp_path / "nope.csv"))["ok"] is False


# ------------------------------------------------------------------ reading reconcile
def test_the_numbers_are_parsed_out_of_reconciles_own_report():
    got = S.parse_reconcile(RECONCILE_OUT)
    assert got["residual"] == pytest.approx(-12.7569)
    assert got["interest_recorded"] == pytest.approx(12.7544)
    assert got["state_equity"] == pytest.approx(100003.65)
    assert got["match"] == 26 and got["missing"] == 0 and got["quantity_diff"] == 0


def test_the_netting_lands_on_zero_and_says_the_sign_is_expected():
    net = S.net_residual(S.parse_reconcile(RECONCILE_OUT))
    assert net["ok"]
    assert net["netted"] == pytest.approx(-0.0025, abs=0.01)
    assert net["within_tolerance"] is True
    assert "negative" in net["expected_sign"]
    assert "CUMULATIVE" in net["cumulative_caveat"]


def test_a_residual_that_is_not_the_interest_is_flagged_not_netted_away():
    rep = S.parse_reconcile(RECONCILE_OUT)
    rep["residual"] = -900.0                     # e.g. a fill nobody confirmed
    net = S.net_residual(rep)
    assert net["netted"] == pytest.approx(-887.25, abs=0.01)
    assert net["within_tolerance"] is False


def test_no_residual_line_is_reported_rather_than_assumed_zero():
    assert S.net_residual({})["ok"] is False


# ------------------------------------------------------------------ the verify_state explainer
CLEAN = "state check: no findings\n"
ARTEFACT = """state check: 2 finding(s)
  ERROR replay_cash      stocks[0] cash stored=6754.09 replay=6754.27
  ERROR replay_cash      etf[0] cash stored=7008.66 replay=7008.89
"""
REAL = """state check: 2 finding(s)
  ERROR replay_cash      stocks[0] cash stored=6754.09 replay=6754.27
  ERROR ledger_order     ledger dates not monotone: 2026-09-09 then 2026-09-08
"""


def test_a_clean_verify_is_reported_clean(tmp_path):
    _state(tmp_path)
    got = S.explain_verify(CLEAN)
    assert got["clean"] is True and got["explained"] is False


def test_anything_other_than_replay_cash_is_never_explained_away(tmp_path):
    _state(tmp_path)
    got = S.explain_verify(REAL)
    assert got["explained"] is False
    assert "ledger_order" in got["reason"]


def _artefact_state(tmp_path, *, break_total=False):
    """The artefact's real shape: interest credited per tranche at accrual time, then the cash
    moved, so stored and replayed disagree PER TRANCHE while the sleeve total is identical.

    Two tranches per sleeve, capital 2000 -> 500 each. One buy of 100.10 in stocks[0] and 12.7544
    of interest on the stocks sleeve, so the sleeve must hold 912.6544 however it is split. Stored
    splits it 405.00 / 507.6544; the weight-based replay splits it differently. That is the whole
    artefact, in fourteen lines.
    """
    stocks_total = 500.0 * 2 - 100.10 + 12.7544
    a, b = 405.00, stocks_total - 405.00
    if break_total:
        b += 50.0                                    # now the sleeve total is wrong: a real break
    st = {
        "last_run_date": "2026-09-08",
        "pending": [],
        "ledger": [{"exec_date": "2026-09-08", "sleeve": "stocks", "tranche": 0, "ticker": "AES",
                    "side": "buy", "status": "filled", "units": 10.0, "price": 10.0,
                    "dollars": 100.0, "cost": 0.1}],
        "interest": [{"date": "2026-09-08", "sleeve": "stocks", "dollars": 12.7544}],
        "sleeves": {
            "stocks": {"tranches": [{"cash": a, "units": {"AES": 10.0}, "last_px": {"AES": 10.0}},
                                    {"cash": b, "units": {}, "last_px": {}}]},
            "etf": {"tranches": [{"cash": 500.0, "units": {}, "last_px": {}},
                                 {"cash": 500.0, "units": {}, "last_px": {}}]},
        },
        "capital_reference": 2000.0, "transfers": [], "write_offs": [],
    }
    d = tmp_path / "state"
    d.mkdir(parents=True, exist_ok=True)
    (d / "portfolio_v9.json").write_text(json.dumps(st), encoding="utf-8")
    S.use_state_dir(str(d))
    return d


def test_replay_cash_alone_is_explained_when_the_sleeve_totals_agree(tmp_path):
    _artefact_state(tmp_path)
    got = S.explain_verify(ARTEFACT)
    assert got["codes"] == ["replay_cash"]
    assert got["explained"] is True, got
    assert got["units_identical"] is True
    assert all(abs(v["diff"]) < 1e-6 for v in got["sleeves"].values())
    assert got["worst_tranche_diff"] > 0, "the fixture must actually differ per tranche"


def test_replay_cash_with_a_broken_sleeve_total_is_NOT_explained_away(tmp_path):
    """The other half of the guard, and the one that matters: a real break must not be dressed up
    as the known artefact just because it arrives under the same code."""
    _artefact_state(tmp_path, break_total=True)
    got = S.explain_verify(ARTEFACT)
    assert got["explained"] is False
    assert "does NOT match" in got["reason"]


def test_the_explainer_never_becomes_the_failure(tmp_path):
    """If the state cannot be replayed the driver says so; it does not raise mid-settle."""
    d = tmp_path / "state"
    d.mkdir()
    (d / "portfolio_v9.json").write_text("{not json", encoding="utf-8")
    S.use_state_dir(str(d))
    got = S.explain_verify(ARTEFACT)
    assert got["explained"] is False and "could not replay" in got["reason"]


# ------------------------------------------------------------------ the snapshot
def test_the_snapshot_is_taken_before_anything_writes(tmp_path):
    d = _state(tmp_path, ledger_dates=("2026-09-08",))
    got = S.snapshot("20260909")
    assert got["ok"] and got["reason"] == "copied"
    assert (d / "backup" / "pre-confirm-20260909.json").exists()


def test_a_second_run_keeps_the_first_snapshot(tmp_path):
    """The first copy is the pre-write state; overwriting it on a re-run would destroy the very
    thing it exists to protect."""
    _state(tmp_path, ledger_dates=("2026-09-08",))
    S.snapshot("20260909")
    again = S.snapshot("20260909")
    assert again["ok"] and "kept the first one" in again["reason"]


def test_no_state_means_no_snapshot_and_no_run(tmp_path):
    S.use_state_dir(str(tmp_path / "empty"))
    assert S.snapshot("20260909")["ok"] is False
