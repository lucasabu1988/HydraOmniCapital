"""Audit phase 5 — store verification, non-destructive backfill, quality metrics.

Reproductions R-501..R-507 in docs/AUDIT_REPRODUCTIONS.md. Fake provider, no network.
"""
import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import reconcile as RC  # noqa: E402
import store_cli  # noqa: E402
from data.store import BarStore  # noqa: E402

IDX = pd.bdate_range("2024-01-02", periods=120)


def _long(ticker="AAA", dates=None, base=100.0, source="fake"):
    dates = list(dates if dates is not None else IDX)
    return pd.DataFrame({
        "ticker": [ticker] * len(dates),
        "date": dates,
        "close_adj": [base + i for i in range(len(dates))],
        "close_raw": [base + i for i in range(len(dates))],
        "volume": [1e6] * len(dates),
        "source": [source] * len(dates),
    })


class Provider:
    """Returns exactly the frame it was handed, filtered to the request."""

    def __init__(self, frame):
        self.df = frame.copy() if frame is not None else pd.DataFrame()

    def fetch(self, tickers, start, end):
        if self.df.empty:
            return pd.DataFrame(columns=["ticker", "date", "close_adj"])
        names = [str(t) for t in tickers]
        sub = self.df[self.df["ticker"].astype(str).isin(names)].copy()
        d = pd.to_datetime(sub["date"]).dt.normalize()
        return sub[(d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))].reset_index(drop=True)


class RawProvider:
    """Returns its frame unfiltered, so a disjoint date range really reaches verify."""

    def __init__(self, frame):
        self.df = frame.copy()

    def fetch(self, tickers, start, end):
        return self.df.copy()


class RaisingProvider:
    def fetch(self, tickers, start, end):
        raise RuntimeError("provider exploded")


def _store(tmp_path, frame=None):
    st = BarStore(tmp_path / "bars.sqlite")
    if frame is not None:
        st.upsert(frame)
    return st


# ------------------------------------------------------------------ R-501
def test_r501_a_short_frame_cannot_shrink_a_long_history(tmp_path):
    """R-501 — phase 5.3. `min_bars=10` was no guard at all: a 12-bar frame passed
    it and cut 2800 stored bars down to 12, silently."""
    st = _store(tmp_path, _long("AAA", IDX))
    first, last, n = st.stored_span("AAA")
    assert n == 120

    short = _long("AAA", pd.bdate_range("2026-01-01", periods=12), base=500.0)
    assert st.replace_ticker("AAA", short) == 0
    assert st.stored_span("AAA") == (first, last, 120)
    st.close()


def test_r501_a_covering_frame_is_allowed_and_archived(tmp_path):
    st = _store(tmp_path, _long("AAA", IDX))
    wider = _long("AAA", pd.bdate_range("2023-01-02", periods=400), base=50.0)
    written = st.replace_ticker("AAA", wider)
    assert written == 400
    assert st.stored_span("AAA")[2] == 400
    snaps = st.archives("AAA")
    assert len(snaps) == 1 and snaps[0]["n_bars"] == 120
    st.close()


def test_r501_the_rollback_restores_the_old_series(tmp_path):
    st = _store(tmp_path, _long("AAA", IDX))
    before = list(st.closes(["AAA"], IDX[0], IDX[-1])["AAA"])
    st.replace_ticker("AAA", _long("AAA", IDX[-30:], base=999.0), allow_shrink=True)
    assert st.stored_span("AAA")[2] == 30
    snap = st.archives("AAA")[0]["snapshot"]
    assert st.restore_ticker(snap) == 120
    after = list(st.closes(["AAA"], IDX[0], IDX[-1])["AAA"])
    assert after == before
    st.close()


def test_merge_never_deletes_and_never_archives(tmp_path):
    st = _store(tmp_path, _long("AAA", IDX))
    later = pd.bdate_range(IDX[-1] + pd.Timedelta(days=1), periods=10)
    st.merge_ticker("AAA", _long("AAA", later, base=900.0))
    assert st.stored_span("AAA")[2] == 130
    assert st.archives("AAA") == []
    st.close()


def test_replace_range_preserves_the_rest_and_the_actions(tmp_path):
    """Phase 5.5."""
    frame = _long("AAA", IDX)
    frame["dividend"] = 0.0
    frame.loc[frame.index[3], "dividend"] = 0.5
    st = _store(tmp_path, frame)
    assert st.dividends(["AAA"], IDX[0], IDX[-1])["AAA"].iloc[0] == pytest.approx(0.5)

    fixed = _long("AAA", IDX[50:60], base=1.0)
    assert st.replace_range("AAA", fixed, IDX[50], IDX[59]) == 10
    assert st.stored_span("AAA")[2] == 120
    assert st.dividends(["AAA"], IDX[0], IDX[-1])["AAA"].iloc[0] == pytest.approx(0.5), \
        "the actions table survives a windowed correction"
    st.close()


# ------------------------------------------------------------------ R-502..R-505
def test_r503_an_empty_store_cannot_be_verified(tmp_path):
    """R-503 — phase 5.1. `verify: store is empty` used to return True (exit 0)."""
    st = _store(tmp_path)
    rep: dict = {}
    assert store_cli._verify(st, 5, provider=Provider(None), report=rep) is False
    assert rep["checked"] == 0
    st.close()


def test_r504_an_empty_provider_response_fails(tmp_path):
    """R-504 — phase 5.1: `provider empty` used to be a per-ticker `continue`."""
    st = _store(tmp_path, _long("AAA", IDX))
    rep: dict = {}
    ok = store_cli._verify(st, 1, provider=Provider(None), names=["AAA"], report=rep)
    assert ok is False
    assert "empty" in " ".join(rep["problems"]).lower()
    st.close()


def test_r505_no_overlap_fails(tmp_path):
    """R-505 — phase 5.1: `no overlap` used to be a per-ticker `continue`."""
    st = _store(tmp_path, _long("AAA", IDX))
    disjoint = _long("AAA", pd.bdate_range("1999-01-04", periods=40), base=10.0)
    rep: dict = {}
    ok = store_cli._verify(st, 1, provider=RawProvider(disjoint), names=["AAA"], report=rep)
    assert ok is False
    assert any("overlap" in p for p in rep["problems"])
    st.close()


def test_r502_a_stored_vs_fresh_discrepancy_fails(tmp_path):
    """R-502 — phase 5.2. `stored_vs_fresh` was computed, printed, then discarded:
    only `local_vs_fresh` gated the exit code, and that needs actions coverage the
    store often does not have."""
    st = _store(tmp_path, _long("AAA", IDX, base=100.0))
    drifted = _long("AAA", IDX, base=100.0)
    drifted.loc[drifted.index[60], "close_adj"] *= 1.5      # a 50% discrepancy
    rep: dict = {}
    ok = store_cli._verify(st, 1, provider=Provider(drifted), names=["AAA"], report=rep)
    assert ok is False
    assert any("stored_vs_fresh" in p for p in rep["problems"])
    assert rep["rows"][0]["stored_vs_fresh"] > 0.4
    st.close()


def test_a_store_that_agrees_with_the_provider_verifies(tmp_path):
    frame = _long("AAA", IDX)
    st = _store(tmp_path, frame)
    rep: dict = {}
    ok = store_cli._verify(st, 1, provider=Provider(frame), names=["AAA"], report=rep)
    assert ok is True
    assert rep["problems"] == []
    assert rep["rows"][0]["n_overlap"] == 120
    st.close()


def test_min_overlap_is_enforced(tmp_path):
    frame = _long("AAA", IDX)
    st = _store(tmp_path, frame)
    thin = frame.iloc[:5]
    rep: dict = {}
    assert store_cli._verify(st, 1, provider=Provider(thin), names=["AAA"],
                             min_overlap=20, report=rep) is False
    assert any("overlap" in p for p in rep["problems"])
    st.close()


def test_min_coverage_is_enforced(tmp_path):
    """Phase 5.1: coverage below the requested fraction is a failure.

    The store holds every second bar of the same span, so the provider offers 120
    bars where the store has 60 — half the sessions inside its own first..last.
    """
    frame = _long("AAA", IDX)
    st = _store(tmp_path, frame.iloc[::2])
    rep: dict = {}
    ok = store_cli._verify(st, 1, provider=Provider(frame), names=["AAA"],
                           min_overlap=20, min_coverage=1.0, report=rep)
    assert ok is False
    assert any("coverage" in p for p in rep["problems"])
    assert rep["rows"][0]["coverage"] == pytest.approx(0.5, abs=0.02)

    rep2: dict = {}
    ok2 = store_cli._verify(st, 1, provider=Provider(frame), names=["AAA"],
                            min_overlap=20, min_coverage=0.4, report=rep2)
    assert ok2 is True
    st.close()


def test_a_provider_that_raises_fails(tmp_path):
    st = _store(tmp_path, _long("AAA", IDX))
    assert store_cli._verify(st, 1, provider=RaisingProvider(), names=["AAA"]) is False
    st.close()


def test_a_provider_frame_missing_columns_fails(tmp_path):
    class Broken:
        def fetch(self, tickers, start, end):
            return pd.DataFrame({"symbol": ["AAA"], "when": [IDX[0]], "px": [1.0]})

    st = _store(tmp_path, _long("AAA", IDX))
    rep: dict = {}
    assert store_cli._verify(st, 1, provider=Broken(), names=["AAA"], report=rep) is False
    assert any("column" in p for p in rep["problems"])
    st.close()


def test_a_ticker_absent_from_the_store_fails(tmp_path):
    st = _store(tmp_path, _long("AAA", IDX))
    frame = _long("BBB", IDX)
    rep: dict = {}
    assert store_cli._verify(st, 1, provider=Provider(frame), names=["BBB"], report=rep) is False
    assert any("not in store" in p for p in rep["problems"])
    st.close()


def test_duplicates_and_non_positive_closes_fail_verification(tmp_path):
    frame = _long("AAA", IDX)
    st = _store(tmp_path, frame)
    st._conn.execute(
        "UPDATE bars SET close_adj=-5.0 WHERE ticker='AAA' AND date=?",
        (str(IDX[10].date()),))
    st._conn.commit()
    rep: dict = {}
    assert store_cli._verify(st, 1, provider=Provider(frame), names=["AAA"], report=rep) is False
    assert any("non-positive" in p for p in rep["problems"])
    st.close()


# ------------------------------------------------------------------ R-506
def test_r506_quality_metrics_exist(tmp_path):
    """R-506 — phase 5.6: first, last, n_bars, gaps, duplicates, discrepancy,
    provider and capture time were all missing."""
    frame = _long("AAA", IDX)
    holed = pd.concat([frame.iloc[:40], frame.iloc[47:]], ignore_index=True)
    st = _store(tmp_path, holed)
    q = st.quality(["AAA"], calendar=IDX)
    row = q.set_index("ticker").loc["AAA"]
    for col in ("first", "last", "n_bars", "gaps", "duplicates", "non_positive",
                "sources", "last_fetched_at", "gap_basis"):
        assert col in q.columns
    assert row["n_bars"] == 113
    assert row["gaps"] == 7
    assert row["sources"] == "fake"
    assert row["last_fetched_at"]
    st.close()


def test_quality_of_an_unknown_ticker_is_reported_not_dropped(tmp_path):
    st = _store(tmp_path, _long("AAA", IDX))
    q = st.quality(["AAA", "NOPE"]).set_index("ticker")
    assert q.loc["NOPE", "n_bars"] == 0
    assert q.loc["NOPE", "first"] is None
    st.close()


def test_stats_exposes_the_new_counters(tmp_path):
    st = _store(tmp_path, _long("AAA", IDX))
    stats = st.stats()
    assert stats["duplicate_rows"] == 0
    assert stats["non_positive_closes"] == 0
    assert stats["archived_snapshots"] == 0
    st.close()


# ------------------------------------------------------------------ R-507
def _write_state(tmp_path):
    state = {
        "schema_version": 1,
        "sleeves": {"stocks": {"tranches": [{"k": 0, "cash": 100.0, "units": {"AAA": 10.0},
                                             "last_px": {"AAA": 10.0}}]},
                    "etf": {"tranches": [{"k": 0, "cash": 50.0, "units": {}, "last_px": {}}]}},
        "ledger": [], "transfers": [], "interest": [], "dividends": [], "write_offs": [],
    }
    p = tmp_path / "portfolio_v9.json"
    p.write_text(json.dumps(state), encoding="utf-8")
    return p


def test_r507_a_missing_csv_exits_non_zero(tmp_path, capsys):
    """R-507 — phase 5.7. Every path in reconcile.main returned 0, including the
    bare `except Exception`, so an unattended run read a broken CSV as clean."""
    state = _write_state(tmp_path)
    rc = RC.main([str(tmp_path / "nope.csv"), "--state", str(state), "--cash-total", "150"])
    assert rc != 0
    assert "not found" in capsys.readouterr().out


def test_r507_an_unparseable_csv_exits_non_zero_with_a_reason(tmp_path, capsys):
    state = _write_state(tmp_path)
    csv = tmp_path / "positions.csv"
    csv.write_text("this is not a csv at all\x00\x00", encoding="utf-8")
    rc = RC.main([str(csv), "--state", str(state), "--cash-total", "150"])
    assert rc != 0
    out = capsys.readouterr().out
    assert "reconcile" in out


def test_r507_an_empty_csv_exits_non_zero(tmp_path, capsys):
    state = _write_state(tmp_path)
    csv = tmp_path / "positions.csv"
    csv.write_text("ticker,units\n", encoding="utf-8")
    rc = RC.main([str(csv), "--state", str(state), "--cash-total", "150"])
    assert rc != 0
    assert "held no positions" in capsys.readouterr().out


def test_r507_a_missing_state_exits_non_zero(tmp_path, capsys):
    csv = tmp_path / "positions.csv"
    csv.write_text("ticker,units\nAAA,10\n", encoding="utf-8")
    rc = RC.main([str(csv), "--state", str(tmp_path / "nope.json"), "--cash-total", "150"])
    assert rc != 0
    assert "state not found" in capsys.readouterr().out


def test_r507_missing_cash_exits_non_zero(tmp_path, capsys):
    state = _write_state(tmp_path)
    csv = tmp_path / "positions.csv"
    csv.write_text("ticker,units\nAAA,10\n", encoding="utf-8")
    rc = RC.main([str(csv), "--state", str(state)])
    assert rc != 0
    assert "cash" in capsys.readouterr().out


def test_r507_a_good_reconciliation_still_exits_zero(tmp_path, capsys):
    state = _write_state(tmp_path)
    csv = tmp_path / "positions.csv"
    csv.write_text("ticker,units\nAAA,10\n", encoding="utf-8")
    rc = RC.main([str(csv), "--state", str(state), "--cash-total", "150"])
    assert rc == 0
    assert "reconcile" in capsys.readouterr().out.lower()


def test_a_corrupt_state_json_exits_non_zero(tmp_path, capsys):
    csv = tmp_path / "positions.csv"
    csv.write_text("ticker,units\nAAA,10\n", encoding="utf-8")
    bad = tmp_path / "portfolio_v9.json"
    bad.write_text("{not json", encoding="utf-8")
    rc = RC.main([str(csv), "--state", str(bad), "--cash-total", "150"])
    assert rc != 0
    assert "cannot read the state" in capsys.readouterr().out


# ------------------------------------------------------------------ CLI
def test_store_cli_quality_exits_non_zero_on_an_empty_store(tmp_path, capsys):
    rc = store_cli.main(["--quality", "--db", str(tmp_path / "bars.sqlite")])
    assert rc == 1
    assert "empty" in capsys.readouterr().out


def test_store_cli_quality_prints_the_table(tmp_path, capsys):
    db = tmp_path / "bars.sqlite"
    st = _store(tmp_path, _long("AAA", IDX))
    st.close()
    rc = store_cli.main(["--quality", "AAA", "--db", str(db)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "AAA" in out and "gaps" in out


def test_store_cli_with_no_action_prints_help(capsys):
    assert store_cli.main([]) == 2
