"""TASK-434 rules, each pinned by a mutation. Synthetic data only; runs on any clone.

Every test names the line of `.comms/prereg-task-434-2026-09-14.md` it enforces (F2..F6, §3).
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capacity as C  # noqa: E402
import engine_backtest as EB  # noqa: E402

IDX = pd.bdate_range("2024-01-01", periods=60)


def _fills(rows):
    """rows: (exec_date, sleeve, tranche, ticker, side, dollars)."""
    return C.fills_frame([dict(exec_date=d, sleeve=s, tranche=tr, ticker=t, side=side, dollars=x,
                               cost=x * 0.001, price=10.0, units=x / 10.0)
                          for d, s, tr, t, side, x in rows])


def _adv(values: dict, index=IDX) -> pd.DataFrame:
    """Constant ADV per ticker across `index`, with explicit NaNs where asked."""
    return pd.DataFrame({t: [v] * len(index) for t, v in values.items()}, index=index, dtype=float)


# ---------------------------------------------------------------- footprints (§3 unit, F6)
def test_footprint_nets_with_sign_across_tranches_and_keeps_gross_as_sensitivity():
    d = str(IDX[10].date())
    f = _fills([(d, "stocks", 0, "AAA", "buy", 100.0), (d, "stocks", 2, "AAA", "sell", 30.0),
                (d, "stocks", 1, "BBB", "buy", 50.0), (d, "etf", 0, "SPY", "buy", 500.0)])
    fp = C.footprints(f).set_index(["sleeve", "ticker"])
    assert fp.loc[("stocks", "AAA"), "net_dollars"] == pytest.approx(70.0)
    assert fp.loc[("stocks", "AAA"), "gross_dollars"] == pytest.approx(130.0)
    assert fp.loc[("stocks", "AAA"), "n_fills"] == 2
    assert len(fp) == 3, "one footprint per (settle, sleeve, ticker), never per micro-fill"


def test_footprints_are_per_settle_never_across_settles():
    f = _fills([(str(IDX[10].date()), "stocks", 0, "AAA", "buy", 100.0),
                (str(IDX[15].date()), "stocks", 0, "AAA", "sell", 100.0)])
    fp = C.footprints(f)
    assert len(fp) == 2 and (fp["net_dollars"].abs() == 100.0).all()


def test_non_trade_sides_are_not_footprints():
    f = _fills([(str(IDX[10].date()), "stocks", 0, "AAA", "transfer_in", 100.0),
                (str(IDX[10].date()), "stocks", 0, "BBB", "buy", 1.0)])
    assert list(C.footprints(f)["ticker"]) == ["BBB"]


# ---------------------------------------------------------------- ADV ex-ante (§3, F2, F3)
def test_adv_is_read_at_the_previous_market_bar_not_the_settle_bar():
    adv = _adv({"AAA": 1.0})
    adv.loc[IDX[10], "AAA"] = 999.0                   # the settle bar's own value
    adv.loc[IDX[9], "AAA"] = 5.0                      # the previous market bar
    assert C.adv_prev_bar(adv, "AAA", IDX[10]) == 5.0
    # mutation: reading at t would return 999 - the realised volume of the execution day
    assert C.adv_prev_bar(adv, "AAA", IDX[10]) != 999.0


def test_previous_bar_is_positional_a_monday_reads_friday():
    monday = IDX[IDX.dayofweek == 0][2]
    friday = IDX[IDX.get_indexer([monday])[0] - 1]
    assert friday.dayofweek == 4
    adv = _adv({"AAA": 1.0})
    adv.loc[friday, "AAA"] = 7.0
    assert C.adv_prev_bar(adv, "AAA", monday) == 7.0


def test_no_previous_bar_unknown_ticker_or_nan_window_are_unknown_never_shortened():
    adv = _adv({"AAA": 3.0})
    adv.iloc[:19, 0] = np.nan                         # the rolling(20) warm-up
    assert math.isnan(C.adv_prev_bar(adv, "AAA", IDX[0])), "first bar has no previous bar"
    assert math.isnan(C.adv_prev_bar(adv, "AAA", IDX[10])), "window not full -> unknown"
    assert not math.isnan(C.adv_prev_bar(adv, "AAA", IDX[20]))
    assert math.isnan(C.adv_prev_bar(adv, "ZZZ", IDX[30])), "ticker absent -> unknown"


def test_zero_volume_becomes_unknown_never_an_infinite_participation():
    close = pd.DataFrame(10.0, index=IDX, columns=["AAA"])
    vol = pd.DataFrame(1000.0, index=IDX, columns=["AAA"])
    vol.iloc[30, 0] = 0.0
    adv = C.adv_panel(close, vol, window=5)
    assert math.isnan(adv.iloc[30, 0]) and math.isnan(adv.iloc[34, 0]) and not math.isnan(adv.iloc[35, 0])
    f = _fills([(str(IDX[31].date()), "stocks", 0, "AAA", "buy", 1.0)])
    fa = C.attach_adv(C.footprints(f), adv)
    assert not bool(fa["known"].iloc[0])
    part = C.participation_pct(fa, 1.0)
    assert part.isna().all(), "unknown stays NaN; it never becomes inf in the descriptive sample"


def test_adv_panel_is_the_labs_one_definition():
    rng = np.random.default_rng(3)
    close = pd.DataFrame(rng.uniform(5, 50, (60, 3)), index=IDX, columns=list("ABC"))
    vol = pd.DataFrame(rng.uniform(1e5, 1e6, (60, 3)), index=IDX, columns=list("ABC"))
    lab = (close * vol).rolling(20).mean()                       # redesign_lab.py:323
    pd.testing.assert_frame_equal(C.adv_panel(close, vol), lab)


# ---------------------------------------------------------------- P95 (§3 order statistic)
@pytest.mark.parametrize("n,unk,finite", [(20, 1, True), (20, 2, False), (21, 1, True), (21, 2, False),
                                          (100, 5, True), (100, 6, False), (1, 0, True), (1, 1, False)])
def test_p95_is_the_explicit_rank_statistic_and_flips_exactly_at_the_documented_unknown_count(n, unk, finite):
    known = np.arange(1.0, n - unk + 1.0)
    q = C.p95_rank(known, unk)
    assert math.isfinite(q) is finite
    if finite:
        k = math.ceil(0.95 * n)
        assert q == float(np.sort(known)[k - 1])


def test_p95_never_interpolates():
    vals = [1.0, 2.0, 3.0, 4.0, 10.0]                 # N=5, k=ceil(4.75)=5 -> the max, not 7.6
    assert C.p95_rank(vals) == 10.0
    assert C.p95_rank(vals) != float(np.quantile(vals, 0.95))     # linear would give 8.8


def test_p95_of_nothing_is_nan_not_zero():
    assert math.isnan(C.p95_rank([]))


# ---------------------------------------------------------------- coverage, breaches, ceiling (§3, F4)
def _fp_adv(n_known=95, n_unknown=5, adv=1_000_000.0, order_frac=0.001):
    d = str(IDX[30].date())
    rows = [(d, "stocks", 0, f"K{i:03d}", "buy", order_frac) for i in range(n_known)]
    rows += [(d, "stocks", 0, f"U{i:03d}", "buy", order_frac) for i in range(n_unknown)]
    adv_df = _adv({f"K{i:03d}": adv for i in range(n_known)})
    return C.attach_adv(C.footprints(_fills(rows)), adv_df)


def test_coverage_is_reported_by_count_and_by_notional():
    fa = _fp_adv(n_known=9, n_unknown=1, order_frac=1.0)
    fa.loc[~fa["known"], "net_dollars"] = 91.0        # one unknown ticket carrying most of the dollars
    cov = C.coverage(fa)
    assert cov["unknown_share_by_count"] == pytest.approx(0.1)
    assert cov["unknown_share_by_notional"] == pytest.approx(0.91)


def test_ceiling_is_not_measurable_when_unknown_share_exceeds_five_percent_by_count():
    fa = _fp_adv(n_known=93, n_unknown=7)              # 7 % unknown by count
    out = C.aum_ceiling(fa, grid=[1e4, 1e5, 1e6])
    assert out["status"] == "NOT MEASURABLE" and out["ceiling_usd"] is None
    assert all(math.isinf(r["p95_conservative"]) for r in out["curve"])
    assert all(math.isfinite(r["p95_descriptive"]) for r in out["curve"]), "descriptive still printed"
    assert out["label"] == C.LABEL


def test_ceiling_is_not_measurable_when_unknown_share_exceeds_five_percent_by_notional_alone():
    fa = _fp_adv(n_known=99, n_unknown=1)              # 1 % by count ...
    fa.loc[~fa["known"], "net_dollars"] = 1.0          # ... but 91 % by notional
    out = C.aum_ceiling(fa, grid=[1e4, 1e5])
    assert out["status"] == "NOT MEASURABLE"
    assert any("notional" in w for w in out["why_not_measurable"])


def test_ceiling_uses_the_conservative_p95_and_brackets_the_grid():
    # 95 known at 0.1 % of capital each vs ADV 1e6 USD: participation(C) = 0.001*C/1e6*100 %
    # -> 3 % bound is crossed at C = 30e6. 5 unknowns (5 %) keep the conservative P95 finite.
    fa = _fp_adv(n_known=95, n_unknown=5)
    grid = [1e6, 1e7, 2e7, 3e7, 4e7, 1e8]
    out = C.aum_ceiling(fa, grid=grid)
    assert out["status"] == "MEASURABLE"
    assert out["ceiling_usd"] == 3e7
    assert out["bracket"] == dict(largest_passing=3e7, smallest_failing=4e7)
    curve = [r["p95_conservative"] for r in out["curve"]]
    assert curve == sorted(curve), "P95 is monotone in capital by construction"


def test_ceiling_with_six_percent_unknown_is_infinite_at_every_capital():
    fa = _fp_adv(n_known=94, n_unknown=6)
    out = C.aum_ceiling(fa, grid=[1e3, 1e9])
    assert not out["measurable"] and all(math.isinf(r["p95_conservative"]) for r in out["curve"])


def test_breaches_count_known_only_and_report_the_unknowns_beside_them():
    part = pd.Series([0.5, 1.5, 3.5, 6.0, np.nan])
    b = C.breaches(part)
    assert b == dict(gt_1pct=0.75, gt_3pct=0.5, gt_5pct=0.25, n_known=4, n_unknown=1)


def test_scenario_table_carries_the_label_on_every_row_at_every_capital():
    fa = _fp_adv(n_known=20, n_unknown=0)
    rows = C.scenario_table(fa)
    assert {r["capital"] for r in rows} == set(C.CAPITALS_USD)
    assert all(r["label"] == C.LABEL for r in rows)
    assert {r["sleeve"] for r in rows} == {"total", "stocks"}


def test_participation_is_linear_in_capital():
    fa = _fp_adv(n_known=10, n_unknown=0)
    a, b = C.participation_pct(fa, 100_000.0), C.participation_pct(fa, 1_000_000.0)
    assert np.allclose(b, a * 10.0)


# ---------------------------------------------------------------- the real sheet
def test_sheet_footprints_read_orders_in_usd_at_planned_or_exec_date(tmp_path):
    sheet = dict(date="2026-09-04", exec_date="2026-09-08",
                 orders=[dict(sleeve="stocks", tranche=0, ticker="SLAB", side="buy", dollars=323.9,
                              planned="2026-09-04"),
                         dict(sleeve="stocks", tranche=0, ticker="SLAB", side="sell", dollars=23.9,
                              planned="2026-09-04"),
                         dict(sleeve="etf", tranche=0, ticker="SPY", side="park", dollars=1.0,
                              planned="2026-09-04")])
    p = tmp_path / "instructions.json"
    p.write_text(json.dumps(sheet), encoding="utf-8")
    fp = C.sheet_footprints(str(p))
    assert len(fp) == 1 and fp["net_dollars"].iloc[0] == pytest.approx(300.0)
    assert str(fp["settle"].iloc[0].date()) == "2026-09-04"
    fx = C.sheet_footprints(str(p), when="exec_date")
    assert str(fx["settle"].iloc[0].date()) == "2026-09-08"


# ---------------------------------------------------------------- the sidecar is an observer
def test_fill_tap_copies_filled_records_and_returns_settles_output_untouched(monkeypatch):
    canned = [dict(exec_date="x", sleeve="stocks", tranche=1, ticker="AAA", side="buy", status="filled",
                   dollars=3.0, cost=0.003, price=1.5, units=2.0),
              dict(sleeve="stocks", tranche=1, ticker="BBB", side="buy", status="not_filled"),
              dict(sleeve="etf", tranche=0, ticker="SPY", side="park", status="noted")]
    calls = []

    def fake_settle(state, exec_date, *a, **kw):
        calls.append(exec_date)
        return canned

    monkeypatch.setattr(EB.E, "settle", fake_settle)
    with C.FillTap() as tap:
        out = EB.E.settle({}, "2024-03-01", None, None, None)
    assert out is canned, "the tap hands back exactly what settle returned"
    assert calls == ["2024-03-01"]
    assert EB.E.settle is fake_settle, "the seam is restored on exit"
    assert len(tap.fills) == 1 and tap.fills[0]["ticker"] == "AAA" and tap.fills[0]["exec_date"] == "2024-03-01"
    tap.fills[0]["dollars"] = 999.0
    assert canned[0]["dollars"] == 3.0, "the tap keeps copies; it cannot edit the engine's records"


def test_payload_has_the_label_at_the_top_and_on_the_ceiling():
    fa = _fp_adv(n_known=20, n_unknown=0)
    p = C.payload(fa, grid=[1e5, 1e6])
    assert p["label"] == C.LABEL and p["ceiling"]["label"] == C.LABEL
    assert "NOT market impact" in p["note"]


def test_aum_grid_is_geometric_and_spans_the_declared_range():
    g = C.aum_grid()
    assert g[0] == 10_000.0 and g[-1] >= 100_000_000.0
    ratios = np.array(g[1:]) / np.array(g[:-1])
    assert np.allclose(ratios, 1.25)


# ---------------------------------------------------------------- F1 (the drive is the accredited drive)
def _reference_from(book, by_step, bp):
    import provenance as PV
    return dict(book_sha256=PV.book_sha256(book), calendar_sha256=PV.calendar_sha256(book.index),
                n_marks=len(book), by_step=by_step, cost_bp_effective_by_sleeve=bp)


def _book_and_ledger():
    book = pd.Series(np.linspace(1.0, 2.0, 12), index=IDX[:12], dtype=float)
    by_step = {str(IDX[3].date()): {"stocks": dict(filled_dollars=0.1, cost_dollars=0.0001, n={}),
                                    "etf": dict(filled_dollars=0.2, cost_dollars=0.0001, n={})},
               str(IDX[8].date()): {"stocks": dict(filled_dollars=0.3, cost_dollars=0.0003, n={})}}
    bp = {"stocks": 10.0, "etf": 5.0}
    return book, by_step, bp


def test_f1_passes_when_values_index_ledger_and_bp_all_agree_even_if_the_container_differs():
    book, by_step, bp = _book_and_ledger()
    ref = _reference_from(book, by_step, bp)
    other_container = pd.Series(book.to_numpy().copy(), index=book.index.copy(), name="renamed")
    out = C.check_f1(ref, other_container, dict(ledger=dict(by_step=by_step, cost_bp_effective_by_sleeve=bp)))
    assert out["passed"] and out["problems"] == [] and out["max_abs_ledger_diff"] == 0.0


@pytest.mark.parametrize("mutation", ["value", "index", "extra_mark", "ledger_dollars", "ledger_date", "bp"])
def test_f1_refuses_each_mutation(mutation):
    import copy
    book, by_step, bp = _book_and_ledger()
    ref = _reference_from(book, by_step, bp)
    b, led, bpm = book.copy(), copy.deepcopy(by_step), dict(bp)
    if mutation == "value":
        b.iloc[5] += 1e-9
    elif mutation == "index":
        b.index = b.index.shift(1, freq="B")
    elif mutation == "extra_mark":
        b = pd.concat([b, pd.Series([2.1], index=[IDX[12]])])
    elif mutation == "ledger_dollars":
        led[str(IDX[3].date())]["stocks"]["filled_dollars"] *= 1 + 1e-9
    elif mutation == "ledger_date":
        led[str(IDX[9].date())] = led.pop(str(IDX[8].date()))
    elif mutation == "bp":
        bpm["etf"] = 8.0
    out = C.check_f1(ref, b, dict(ledger=dict(by_step=led, cost_bp_effective_by_sleeve=bpm)))
    assert not out["passed"] and out["problems"], mutation
