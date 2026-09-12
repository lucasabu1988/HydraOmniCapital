"""TASK-433: the cost table is deltas against base, the four scenarios are the declared ones, and
the T-bill flag fires when a scenario's ann_net drops under the risk-free. No engine, no network:
the driver is injected and the base books are synthetic.

One test deliberately does NOT inject the risk-free series: it writes a percent-valued `irx.pkl`
to a tmp cache and lets `run` take the load-from-file branch, because that branch is the one that
shipped the bug (the file is percent, `metrics.step_risk_free` wants decimal) and an injected
0.015 proves nothing about it.

The synthetic base books are ACCREDITED in the fixture - a manifest is written beside each - so
every test here goes through the validator rather than round a cache path that only checks a
filename. The per-scenario rejection cases live in `test_provenance.py`; what is tested here is
the wiring: that `run` refuses an unaccredited book, that it seals every book it drives, that the
mark grid is checked whatever route the books came in by, and that the drive path keeps the
counts it used to throw away.

Auto-discovered by run_all_tests.py (pytest-routed: no __main__ block)."""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cost_stress as CS  # noqa: E402
import provenance as PV  # noqa: E402
import engine_backtest as EB  # noqa: E402


def _book(drift_per_step: float, n: int = 300, seed: int = 433) -> pd.Series:
    rng = np.random.default_rng(seed)
    r = drift_per_step + 0.01 * rng.standard_normal(n)
    idx = pd.bdate_range("2010-06-28", periods=n * 5)[::5]
    return pd.Series(np.cumprod(1 + r), index=idx)


def _stub_run_env(tmp_path, monkeypatch):
    """Everything `run` touches except the risk-free series: scratch dirs, base books, driver.

    Returned so a test can look at the per-scenario cache. The risk-free leg is left alone on
    purpose - each test decides whether to inject it or make `run` read a file.
    """
    out = tmp_path / "cs"
    monkeypatch.setattr(CS, "OUT_DIR", str(out))
    monkeypatch.setattr(CS, "SCRATCH", str(tmp_path / "task433.json"))
    base_r, base_s = tmp_path / "rus.pkl", tmp_path / "sp.pkl"
    pd.to_pickle(_book(0.0016), base_r)                  # ~8%/yr
    pd.to_pickle(_book(0.0020, seed=7), base_s)
    monkeypatch.setattr(CS, "BASE_BOOKS", {"russell": str(base_r), "sp500": str(base_s)})

    # The expected grid is derived from the real panel, which a unit test must not load. The
    # stub returns the grid the stub books actually sit on, so `check_grid` runs for real and
    # agrees; tests that want a MISMATCH override this with a grid of their own.
    def fake_spec(panel):
        marks = pd.DatetimeIndex(pd.read_pickle(base_r).index)
        return dict(marks=marks, n_marks=len(marks), start_bar=280, warmup=280, step=5,
                    tail_bars=6, calendar_source="stub", rules={"stub": True},
                    basis="stub", calendar_identity="stub")
    monkeypatch.setattr(CS, "derived_grid", fake_spec)

    # the injected driver: heavier costs shave the drift, the crisis scenario goes under the T-bill
    def fake_drive(panel, s_bp, e_bp, *, start_date=None, drive_fn=None):
        # same seed as the base book: only the drift moves, so the deltas are the cost effect and
        # not the noise of a different draw (a per-scenario seed made `conservative` beat `base`).
        drift = {10.0: 0.0016, 20.0: 0.0012, 35.0: 0.0006, 50.0: -0.0004}[s_bp]
        return _book(drift)
    monkeypatch.setattr(CS, "drive", fake_drive)

    # a few-KB stand-in for the panel: the real caches are 264 MB each and are never opened here
    panel = tmp_path / "close.pkl"
    pd.to_pickle(pd.DataFrame({"AAA": [1.0] * 4, "BBB": [2.0] * 4},
                              index=pd.bdate_range("2010-06-28", periods=4)), panel)
    monkeypatch.setattr(CS, "data_inputs",
                        lambda p: dict(price_close=str(panel), membership=None))
    # the base books are sealed, so the tests below exercise the accredited path end to end
    for panel_name, book_path in (("russell", base_r), ("sp500", base_s)):
        CS.PV.write_manifest(pd.read_pickle(book_path), str(book_path),
                             CS.request(panel_name, "base", 10.0, 5.0))
    return out


def test_scenarios_are_the_declared_four():
    assert [s[0] for s in CS.SCENARIOS] == ["base", "conservative", "stress", "smallcap_crisis"]
    assert [(s[1], s[2]) for s in CS.SCENARIOS] == [(10.0, 5.0), (20.0, 8.0), (35.0, 10.0), (50.0, 15.0)]


def test_cost_override_sets_and_restores_v9():
    before = (EB.V9["stock_cost_bp"], EB.V9["etf_cost_bp"])
    with CS._CostOverride(35.0, 10.0):
        assert (EB.V9["stock_cost_bp"], EB.V9["etf_cost_bp"]) == (35.0, 10.0)
    assert (EB.V9["stock_cost_bp"], EB.V9["etf_cost_bp"]) == before


def test_table_is_deltas_vs_base_and_flags_below_tbill(tmp_path, monkeypatch, capsys):
    out = _stub_run_env(tmp_path, monkeypatch)

    idx = pd.bdate_range("2010-01-01", "2016-12-31")
    irx = pd.Series(0.015, index=idx)                     # 1.5% T-bill as the DECIMAL annual rate
                                                          # (P.IRX/irx.pkl convention; metrics divides it by 252)
    payload = CS.run(irx=irx, panels=("russell",))

    rows = payload["rows"]
    assert [r["scenario"] for r in rows] == ["base", "conservative", "stress", "smallcap_crisis"]
    base = rows[0]
    assert base["d_ann_net"] == 0.0 and base["d_sharpe_excess"] == 0.0 and base["d_maxdd"] == 0.0
    for r in rows[1:]:
        assert abs(r["d_ann_net"] - (r["ann_net"] - base["ann_net"])) < 1e-6
        assert r["d_ann_net"] < 0, "heavier costs must not raise ann_net in the fake"
    assert rows[-1]["below_tbill"] is True and base["below_tbill"] is False
    # the flag names every scenario under the T-bill, in order, and the base is not one of them
    assert payload["below_tbill"] == ["russell/stress", "russell/smallcap_crisis"]
    printed = capsys.readouterr().out
    assert "BELOW T-BILL: russell/stress, russell/smallcap_crisis" in printed
    # books cached per scenario, base not duplicated
    assert (out / "russell_conservative.pkl").exists() and not (out / "russell_base.pkl").exists()
    assert payload["holdout"]["declared"] == "research+validation"


def test_run_reads_irx_from_file_as_percent_and_consumes_it_as_decimal(tmp_path, monkeypatch):
    """The load-from-file branch, which is where the unit is declared and where the bug lived.

    `irx.pkl` holds ^IRX annualised in PERCENT; `metrics.step_risk_free` compounds an annualised
    DECIMAL rate. Reading the file raw published a 342 % T-bill and stamped `below_tbill` on
    every row of TASK-433. A flat 1.5 % file makes the right answer checkable by hand.
    """
    out = _stub_run_env(tmp_path, monkeypatch)
    cache = tmp_path / "oos_cache"
    cache.mkdir()
    pd.to_pickle(pd.Series(1.5, index=pd.bdate_range("2010-01-01", "2016-12-31"), name="IRX"),
                 cache / "irx.pkl")
    monkeypatch.setattr(CS.R, "OOS_CACHE", str(cache))

    seen = []
    real_step_rf = CS.M.step_risk_free

    def spy(irx, dates, *a, **kw):
        seen.append(pd.Series(irx).astype(float))
        return real_step_rf(irx, dates, *a, **kw)
    monkeypatch.setattr(CS.M, "step_risk_free", spy)

    payload = CS.run(panels=("russell",))            # no irx=: the file is read, not injected

    assert seen, "no row reached step_risk_free: the load-from-file branch did not run"
    # what the statistics actually consume. 1.5 would be the raw file (the 342 % bug) and
    # 0.00015 a second division; only 0.015 is the decimal contract.
    assert float(seen[0].max()) == pytest.approx(0.015, rel=1e-12)
    rf = payload["rows"][0]["rf_ann_pct"]
    assert rf == pytest.approx(1.5112, abs=0.001)    # ((1 + 0.015/252)**252 - 1) * 100
    assert 1.0 < rf < 2.0                            # the band: ~342 if the /100 is dropped
    assert (out / "russell_stress.pkl").exists()


def test_load_annual_rate_requires_a_declared_unit_and_never_sniffs(tmp_path):
    p = tmp_path / "rate.pkl"
    pd.to_pickle(pd.Series(5.0, index=pd.bdate_range("2020-01-01", periods=10)), p)
    assert float(CS.load_annual_rate(p, unit="percent").iloc[0]) == 0.05
    # the same 5.0 declared DECIMAL comes back untouched: there is no magnitude rule to trip
    assert float(CS.load_annual_rate(p, unit="decimal").iloc[0]) == 5.0
    with pytest.raises(ValueError):
        CS.load_annual_rate(p, unit="pct")
    with pytest.raises(TypeError):
        CS.load_annual_rate(p)                       # the unit is not optional
    cal = pd.bdate_range("2020-01-01", periods=12)   # two bars past the end of the file
    onto = CS.load_annual_rate(p, unit="percent", calendar=cal)
    assert list(onto.index) == list(cal) and float(onto.iloc[-1]) == 0.05      # ffilled, not NaN


def test_as_annual_decimal_divides_a_sub_one_percent_print():
    # the ZIRP trap that kills every heuristic: 0.085 and -0.105 are real ^IRX prints (the 25th
    # percentile and the minimum of the shipped file), both legitimate PERCENT and both under 1.
    s = pd.Series([0.085, -0.105], index=pd.bdate_range("2021-01-01", periods=2))
    assert [round(v, 6) for v in CS.as_annual_decimal(s, unit="percent")] == [0.00085, -0.00105]


def test_deltas_are_taken_before_any_rounding():
    """The published quantity is a difference of tenths; rounding the inputs first destroys it."""
    base = dict(ann_net=5.6638, sharpe_excess=0.4878, maxdd_net=-16.0065)
    row = dict(ann_net=5.0630, sharpe_excess=0.4249, maxdd_net=-17.1619)
    d = CS.deltas(row, base)
    assert d["d_sharpe_excess"] == pytest.approx(-0.0629, abs=1e-9)   # -0.07 from rounded inputs
    assert d["d_maxdd"] == pytest.approx(-1.1554, abs=1e-9)           # -1.2  from rounded inputs
    assert d["d_ann_net"] == pytest.approx(-0.6008, abs=1e-9)


# --------------------------------------------------------- the cache is a comparison, not a stat

def test_an_unaccredited_book_stops_the_run_and_says_why(tmp_path, monkeypatch):
    """Existence must never be a cache hit, and refusing is the default, not the option.

    This is the state the eight published books are actually in: driven before any manifest
    existed, so there is nothing to compare them against and nothing to invent. The run stops.
    """
    out = _stub_run_env(tmp_path, monkeypatch)
    os.remove(CS.PV.manifest_path(CS.BASE_BOOKS["russell"]))
    idx = pd.bdate_range("2010-01-01", "2016-12-31")
    with pytest.raises(SystemExit) as e:
        CS.run(irx=pd.Series(0.015, index=idx), panels=("russell",))
    msg = str(e.value)
    assert "CACHE UNACCREDITED [manifest]" in msg
    assert "never consumed as a cache hit" in msg
    assert "--allow-historical" in msg
    assert os.path.exists(CS.BASE_BOOKS["russell"])      # the old file is preserved
    assert not (out / "russell_conservative.pkl").exists(), "nothing was driven past the refusal"


def test_allow_historical_consumes_the_old_book_but_stamps_every_row(tmp_path, monkeypatch, capsys):
    """The escape hatch is explicit, labelled, and cannot be mistaken for an accredited result."""
    _stub_run_env(tmp_path, monkeypatch)
    os.remove(CS.PV.manifest_path(CS.BASE_BOOKS["russell"]))
    idx = pd.bdate_range("2010-01-01", "2016-12-31")
    payload = CS.run(irx=pd.Series(0.015, index=idx), panels=("russell",), allow_historical=True)

    assert payload["rows"][0]["provenance"] == CS.PV.HISTORICAL
    assert payload["provenance"]["historical_incomplete"] == ["russell/base"]
    assert payload["provenance"]["fully_accredited"] is False
    # the books driven in the same run ARE accredited: the two classes coexist and are reported
    assert payload["rows"][1]["provenance"] == CS.PV.ACCREDITED
    printed = capsys.readouterr().out
    assert "CACHE UNACCREDITED: russell/base" in printed
    assert "TASK-433 stays open" in printed


def test_a_cached_book_priced_at_other_costs_is_refused_not_reused(tmp_path, monkeypatch):
    """The wiring of rejection (i): a scenario book sealed at 20/8, asked for at 35/10.

    The file is left exactly as it is - a validator that repaired the cache by overwriting would
    destroy the artifact it was meant to protect.
    """
    out = _stub_run_env(tmp_path, monkeypatch)
    idx = pd.bdate_range("2010-01-01", "2016-12-31")
    irx = pd.Series(0.015, index=idx)
    CS.run(irx=irx, panels=("russell",))                       # drives + seals every scenario

    stress = out / "russell_stress.pkl"
    before = CS.PV.book_sha256(pd.read_pickle(stress))
    man = CS.PV.read_manifest(str(stress))
    man["costs"]["stock_bp_per_side"], man["costs"]["etf_bp_per_side"] = 20.0, 8.0
    with open(CS.PV.manifest_path(str(stress)), "w", encoding="utf-8") as fh:
        json.dump(CS.PV.seal(man), fh, indent=2, default=str)

    with pytest.raises(SystemExit) as e:
        CS.run(irx=irx, panels=("russell",))
    msg = str(e.value)
    assert "CACHE REJECTED [costs]" in msg
    assert "stored stock_bp=20.0 etf_bp=8.0" in msg and "requested stock_bp=35.0 etf_bp=10.0" in msg
    assert "left exactly as it is" in msg
    assert CS.PV.book_sha256(pd.read_pickle(stress)) == before


def test_every_book_the_script_drives_gets_a_manifest_beside_it(tmp_path, monkeypatch):
    out = _stub_run_env(tmp_path, monkeypatch)
    idx = pd.bdate_range("2010-01-01", "2016-12-31")
    CS.run(irx=pd.Series(0.015, index=idx), panels=("russell",))
    for label in ("conservative", "stress", "smallcap_crisis"):
        book = out / f"russell_{label}.pkl"
        assert book.exists() and os.path.exists(CS.PV.manifest_path(str(book)))
        man = CS.PV.read_manifest(str(book))
        assert CS.PV.seal_ok(man)[0], "the manifest must verify against itself"
        assert man["costs"]["scenario_label"] == label
        # the pair, never the blend: 20/8 and 15/13 must not collapse to one 14.0 bp number
        assert (man["costs"]["stock_bp_per_side"], man["costs"]["etf_bp_per_side"]) == \
            dict((s[0], (s[1], s[2])) for s in CS.SCENARIOS)[label]
        assert man["units"]["irx"]["divisor"] == 100.0
        assert man["result"]["sha256"] == CS.PV.book_sha256(pd.read_pickle(book))
        assert man["calendar"]["n_marks"] == len(pd.read_pickle(book))
    # and a second run consumes them through the validator rather than by filename
    payload = CS.run(irx=pd.Series(0.015, index=idx), panels=("russell",))
    # Every book comes back through the validator, not by filename. The ANCHOR is the exception
    # and must stay one: it defines the mark grid, so its window is compared against nothing.
    # This line used to read `all(... == ACCREDITED)`, which asserted the defect as correct -
    # an uncompared mandatory calendar passing as full accreditation. The contract is now that
    # the anchor is degraded and every book compared against it is accredited.
    by_scenario = {r["scenario"]: r["provenance"] for r in payload["rows"]}
    # The anchor is no longer an exception. It used to be exempt ("nothing to compare it to") and
    # was then marked DEGRADED for that reason; now the grid is DERIVED from the rules before any
    # book is opened, so the first book is validated like every other and can be fully accredited.
    assert all(v == CS.PV.ACCREDITED for v in by_scenario.values())
    assert payload["provenance"]["fully_accredited"] is True
    assert "no book validates its own grid" in payload["provenance"]["calendar_validated_against"]


def test_the_cache_line_reports_a_class_and_never_a_bare_boolean(tmp_path, monkeypatch, capsys):
    """`os.path.exists` printed as a status IS the defect, written down."""
    out = _stub_run_env(tmp_path, monkeypatch)
    payload = CS.run(dry_run=True, panels=("russell",))
    assert payload["cached"]["russell"]["base"] == CS.PV.ACCREDITED
    assert payload["cached"]["russell"]["stress"] == "absent"
    assert "True" not in capsys.readouterr().out.split("cache:")[1].splitlines()[0]
    assert not (out / "russell_stress.pkl").exists()


def test_the_mark_grid_identity_is_checked_automatically(tmp_path, monkeypatch):
    """Every delta in the table is a subtraction between two books; on different grids it is not
    a delta at all. The check runs on the books as consumed, so it covers the historical route
    too, where there is no manifest whose calendar could be compared."""
    _stub_run_env(tmp_path, monkeypatch)
    idx = pd.bdate_range("2010-01-01", "2016-12-31")
    payload = CS.run(irx=pd.Series(0.015, index=idx), panels=("russell",))
    assert payload["marks"]["identical"] is True
    assert payload["marks"]["n_books"] == 4 and payload["marks"]["n_marks"] == 300
    assert payload["marks"]["sha256"] == CS.PV.calendar_sha256(
        pd.read_pickle(CS.BASE_BOOKS["russell"]).index)


def test_a_book_on_a_different_grid_stops_the_table(tmp_path, monkeypatch):
    _stub_run_env(tmp_path, monkeypatch)
    short = _book(0.0016)[:200]
    monkeypatch.setattr(CS, "drive", lambda *a, **k: short)
    idx = pd.bdate_range("2010-01-01", "2016-12-31")
    with pytest.raises(SystemExit) as e:
        CS.run(irx=pd.Series(0.015, index=idx), panels=("russell",))
    msg = str(e.value)
    assert "MARK GRID MISMATCH" in msg
    assert "russell/conservative is 200 marks" in msg and "russell/base is 300 marks" in msg
    assert "on different grids it is not a delta" in msg


# --------------------------------------------------------------- what the drive path now keeps

def test_the_ledger_tap_measures_fills_per_sleeve_without_touching_the_engine():
    """The counts stop being thrown away at `book, _ = drive_fn(...)`.

    Everything measured here already exists on the fill records the engine writes; the tap only
    wraps `settle` for the duration of one drive, which is the seam `run_russell_prereg` already
    uses. `cost_bp_effective_by_sleeve` is the self-check: it must equal the configured bp, so a
    broken cost override shows up as a number instead of as a silently wrong table.
    """
    before = EB.E.settle
    with CS._LedgerTap() as tap:
        assert EB.E.settle is not before, "settle was not wrapped"
        EB.E.settle({"pending": []}, "2020-01-08", None, None)
    assert EB.E.settle is before, "settle was not restored"

    tap = CS._LedgerTap()
    tap._record("2020-01-08", [
        dict(sleeve="stocks", side="buy", status="filled", dollars=1000.0, cost=1.0),
        dict(sleeve="stocks", side="sell", status="filled", dollars=500.0, cost=0.5),
        dict(sleeve="etf", side="buy", status="filled", dollars=400.0, cost=0.2),
        dict(sleeve="stocks", side="buy", status="not_filled"),
    ])
    tap._record("2020-01-15", [
        dict(sleeve="etf", side="sell", status="filled", dollars=200.0, cost=0.1),
    ])
    s = tap.summary()
    assert s["settles"] == 2
    assert s["by_sleeve"]["stocks"]["filled_dollars"] == 1500.0
    assert s["by_sleeve"]["stocks"]["cost_dollars"] == 1.5
    assert s["by_sleeve"]["etf"]["filled_dollars"] == 600.0
    assert s["by_sleeve"]["stocks"]["events"]["buy:not_filled"] == 1
    # 1.5 / 1500 = 10 bp per side on stocks, 0.3 / 600 = 5 bp on ETFs: the configured pair,
    # measured out of the fills rather than assumed from the config
    assert s["cost_bp_effective_by_sleeve"]["stocks"] == pytest.approx(10.0, abs=1e-9)
    assert s["cost_bp_effective_by_sleeve"]["etf"] == pytest.approx(5.0, abs=1e-9)


def test_turnover_is_measured_against_the_book_and_is_not_the_inferred_number():
    """Per-sleeve turnover at full precision, and named for what it is.

    The engine's own `counts['turnover']` is mean PLANNED buy+sell dollars over the book total,
    rounded to 1 dp; the 10.87 % + 1.22 % quoted last cycle was BACK-SOLVED from the cost deltas
    of these same books under an assumed 50/50 blend. This is a third quantity - filled dollars -
    and `INFERENCE_RULE` says why agreement between any two of them is arithmetic rather than
    confirmation.
    """
    book = pd.Series([100.0, 100.0], index=pd.to_datetime(["2020-01-06", "2020-01-13"]))
    tap = CS._LedgerTap()
    tap._record("2020-01-07", [dict(sleeve="stocks", side="buy", status="filled",
                                    dollars=10.0, cost=0.01)])
    tap._record("2020-01-14", [dict(sleeve="stocks", side="buy", status="filled",
                                    dollars=20.0, cost=0.02)])
    s = tap.summary(book)
    # 10/100 and 20/100 -> mean 15 % of the book per step, unrounded
    assert s["turnover_filled_pct_by_sleeve"]["stocks"] == pytest.approx(15.0, abs=1e-12)
    assert s["turnover_filled_pct_total"] == pytest.approx(15.0, abs=1e-12)
    assert "NOT the algebraic back-solve" in s["measured"]
    assert "never independent evidence" in CS.INFERENCE_RULE


def test_drive_returns_the_counts_it_used_to_discard(tmp_path, monkeypatch):
    """`drive` hands back `(book, measured)`; the seam that made this possible is the tap, so it
    works for the S&P panel too, whose driver returns a bare Series."""
    book = _book(0.0016)
    seen = {}

    class FakePanel:
        close = pd.DataFrame({"AAA": [1.0]}, index=pd.to_datetime(["2010-06-28"]))
        SECTOR_SOURCE = dict(mode="fixed", pit_valid=False, snapshot_date="2026-09-10",
                             n_mapped=3, n_fallback=1)
        SECTOR = {"AAA": "Tech"}

    monkeypatch.setattr(CS, "load_russell_panel", lambda: (FakePanel(), lambda: None, 280))

    def fake_engine(P, **kw):
        seen["stock_bp"] = EB.V9["stock_cost_bp"]
        return book, dict(turnover=12.7, plans=814)

    got, measured = CS.drive("russell", 35.0, 10.0, drive_fn=fake_engine)
    assert got is book
    assert seen["stock_bp"] == 35.0                       # the override was live during the drive
    assert measured["engine_counts"]["turnover"] == 12.7  # no longer dropped at `book, _ = ...`
    assert measured["start_bar"] == 280
    assert measured["sectors"]["requested_mode"] == "fixed"
    assert measured["sectors"]["n_fallback"] == 1
    assert measured["universe"]["n_columns"] == 1
    assert "ledger" in measured


# ------------------------------------------------------------- the eight books that came before

def test_the_existing_books_are_classified_historical_and_never_accredited(tmp_path, monkeypatch):
    """No fabricated retrospective metadata: the sidecar records what is observable now and says,
    in the file, that agreement with the TASK-431 row is corroboration and not proof."""
    books = []
    for name in ("engine_book_russell.pkl", "russell_stress.pkl"):
        p = tmp_path / name
        pd.to_pickle(_book(0.0016), p)
        books.append(str(p))
    out = CS.classify_existing_books(books)

    assert len(out) == 2
    for p in books:
        assert os.path.exists(CS.PV.provenance_path(p))
        assert not os.path.exists(CS.PV.manifest_path(p)), "classification is not accreditation"
        assert CS.PV.classify(p) == CS.PV.HISTORICAL
        rec = json.load(open(CS.PV.provenance_path(p), encoding="utf-8"))
        assert rec["cls"] == CS.PV.HISTORICAL
        assert "NOT proof of provenance" in rec["corroboration"]
        kinds = {e["kind"] for e in rec["contemporaneous_evidence"]}
        assert {"artifact", "run_log", "inputs", "code_mtimes", "protocol", "absent"} <= kinds
        # the one item that does not merely fail to support code identity, but breaks it
        broke = [e for e in rec["contemporaneous_evidence"] if e["kind"] == "code_mtimes"][0]
        assert "BREAKS it" in broke["does_not_support"]
        assert "result.sha256" in rec["absent"]


def test_classifying_twice_leaves_an_accredited_book_alone(tmp_path, monkeypatch):
    _stub_run_env(tmp_path, monkeypatch)
    path = CS.BASE_BOOKS["russell"]                       # sealed by the fixture
    CS.classify_existing_books([path])
    assert CS.PV.classify(path) == CS.PV.ACCREDITED
    assert not os.path.exists(CS.PV.provenance_path(path))


# --- the publisher must carry per-book limitations into the aggregate --------------------
#
# The defect: `accredit` returns a record naming every block it could not compare, the call site
# bound it to `_man` and dropped it, anything that did not RAISE was stamped ACCREDITED, and
# `fully_accredited` was "no historical rows". A book accepted under `calendar_anchor` - window
# compared against nothing - therefore landed inside fully_accredited=true, with the warning
# living only on stdout. These pin the artifact, not the console.

def _acc(uncompared, why=None):
    """An accreditation record: every identity block compared EXCEPT the ones named.

    `compared` must carry positive evidence for each mandatory block - silence is not agreement -
    so the fixture lists them all and removes only what the case is about.
    """
    uncompared = list(uncompared)
    compared = [b for b in PV.IDENTITY_BLOCKS if b not in uncompared]
    return {"_accreditation": {"compared": compared, "uncompared": uncompared,
                               "uncompared_why": why or {}, "uncompared_keys": [], "degraded": []}}


def test_a_book_whose_calendar_went_uncompared_is_not_plainly_accredited():
    cls, lim = CS.classify_accreditation(
        _acc(["calendar"], {"calendar": "declared anchor: this book DEFINES the grid"}))
    assert cls == CS.DEGRADED
    assert lim["identity_blocks_not_compared"] == ["calendar"]
    assert "stdout warning does not discharge" in lim["note"]


def test_a_fully_compared_book_is_accredited_with_no_limitation():
    cls, lim = CS.classify_accreditation(_acc([]))
    assert cls == PV.ACCREDITED and lim is None


def test_a_non_identity_block_left_uncompared_does_not_degrade():
    """`universe` is DERIVED - its identity rides on data:price_close, which IS compared."""
    cls, lim = CS.classify_accreditation(_acc(["universe"]))
    assert cls == PV.ACCREDITED and lim is None


def test_every_identity_block_gates_the_aggregate():
    for block in PV.IDENTITY_BLOCKS:
        cls, lim = CS.classify_accreditation(_acc([block]))
        assert cls == CS.DEGRADED, f"{block} must not pass as fully accredited"
        assert block in lim["identity_blocks_not_compared"]


def test_a_truncated_anchor_is_rejected_end_to_end(tmp_path, monkeypatch):
    """The attack the module exists to stop, driven through the integrated path to the JSON.

    A book whose marks do not sit on the grid the rules produce must not reach the artifact as
    accredited - and the first book is the one that used to be exempt.
    """
    _stub_run_env(tmp_path, monkeypatch)
    full = pd.DatetimeIndex(pd.read_pickle(CS.BASE_BOOKS["russell"]).index)

    def truncated_spec(panel):
        marks = full.append(pd.DatetimeIndex([full[-1] + pd.Timedelta(days=5)]))  # grid has more
        return dict(marks=marks, n_marks=len(marks), start_bar=280, warmup=280, step=5,
                    tail_bars=6, calendar_source="stub", rules={"stub": True},
                    basis="stub", calendar_identity="stub")
    monkeypatch.setattr(CS, "derived_grid", truncated_spec)

    idx = pd.bdate_range("2010-01-01", "2016-12-31")
    # The refusal is harder than a limitation: the derived grid is now the anchor's reference, so
    # a book that does not answer for it is rejected by `accredit` and the run publishes NOTHING.
    with pytest.raises(SystemExit, match=r"CACHE REJECTED \[calendar\]"):
        CS.run(irx=pd.Series(0.015, index=idx), panels=("russell",))
    assert not os.path.exists(CS.SCRATCH), "a rejected run must not leave a published artifact"


def test_a_valid_run_reaches_the_json_with_the_checks_satisfied(tmp_path, monkeypatch):
    """The positive control: books on the derived grid publish fully_accredited=true."""
    _stub_run_env(tmp_path, monkeypatch)
    idx = pd.bdate_range("2010-01-01", "2016-12-31")
    payload = CS.run(irx=pd.Series(0.015, index=idx), panels=("russell",))
    prov = payload["provenance"]
    assert prov["fully_accredited"] is True
    assert prov["limitations"] == [] and prov["accredited_with_limitations"] == []
    assert len(prov["accredited"]) == len(payload["rows"])
    on_disk = json.load(open(CS.SCRATCH, encoding="utf-8"))
    assert on_disk["provenance"]["fully_accredited"] is True
    assert "derived from the input data" in on_disk["provenance"]["calendar_validated_against"]


def test_the_two_input_defects_are_refused_through_the_integrated_path(tmp_path, monkeypatch):
    """Codex's two calendar_spec defects, reached from the publisher rather than the helper."""
    _stub_run_env(tmp_path, monkeypatch)
    idx = pd.bdate_range("2010-01-01", "2016-12-31")

    # (a) the grid cannot be derived at all -> the run must not publish full accreditation
    monkeypatch.setattr(CS, "derived_grid",
                        lambda panel: (_ for _ in ()).throw(ValueError("calendar is empty")))
    # With no derivable grid there is no reference, so the request declares no calendar and
    # `accredit` refuses the undeclared identity block rather than publishing an accreditation.
    with pytest.raises(SystemExit, match=r"CACHE REJECTED \[calendar\]"):
        CS.run(irx=pd.Series(0.015, index=idx), panels=("russell",))
    assert not os.path.exists(CS.SCRATCH)

    # (b) an empty candidate against a real grid is not agreement
    full = pd.DatetimeIndex(pd.read_pickle(CS.BASE_BOOKS["russell"]).index)
    spec = dict(marks=full, n_marks=len(full), start_bar=280, warmup=280, step=5, tail_bars=6,
                calendar_source="stub", rules={}, basis="stub", calendar_identity="stub")
    r = CS.CSPEC.validate_marks(pd.DatetimeIndex([]), spec)
    assert r["ok"] is False and "empty book is not a match" in r["problems"][0]
