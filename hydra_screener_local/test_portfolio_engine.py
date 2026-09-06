"""HYDRA v9 engine: hand-computable cases, idempotence, and parity with the executable simulator.

The parity tests need the lab caches (experiments/_sweep_cache*, gitignored) and skip without them.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import V9  # noqa: E402
import core.portfolio_engine as E  # noqa: E402

CFG = dict(V9, tranches=2, step_bars=1, hold_bars=2, stock_cost_bp=0.0, etf_cost_bp=0.0, max_stale_bars=10)
DATES = pd.bdate_range("2026-01-05", periods=8)


def _ranking(names, n=None, sectors=None, vetoed=()):
    n = len(names) if n is None else n
    return pd.DataFrame({"ticker": names, "rank": range(1, len(names) + 1),
                         "sector": [sectors.get(t, "Other") if sectors else "Other" for t in names],
                         "recommended": [i < n for i in range(len(names))],
                         "reason": ["Vetado: caída reciente" if t in vetoed else "" for t in names],
                         "recommended_count": n})


def _prices(cols, rows):
    return pd.DataFrame(rows, index=DATES[:len(rows)], columns=cols, dtype=float)


def test_reference_case_book_is_flat_and_reset_is_recorded():
    # stocks tranche 0 buys A (100 -> 200 -> 100); ETF sleeve stays in T-bill (all off). Capital 800.
    st = E.new_state(800.0, str(DATES[0].date()), CFG)
    stock_px = _prices(["A"], [[100], [100], [200], [100], [100]])
    etf_px = _prices(["SPY"], [[100]] * 5)                       # not eligible (no 252 bars) -> empty targets
    # week 0 (anchor bar): renew tranche 0 with A at full exposure (single name: basket vol from 1 bar -> expo 1)
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(["A"]), stock_px.iloc[:1], etf_px.iloc[:1], 0.0, CFG)
    sides = {(o["sleeve"], o["side"]) for o in orders}
    assert ("stocks", "buy") in sides and ("etf", "park") in sides
    buy = next(o for o in orders if o["side"] == "buy")
    assert buy["dollars"] == pytest.approx(800 / 4)              # renewed tranche = 1/8 of the book... of 800 = 100? no: 2 tranches -> 1/4
    E.settle(st, str(DATES[1].date()), stock_px.iloc[1], etf_px.iloc[1], CFG)
    assert st["sleeves"]["stocks"]["tranches"][0]["units"]["A"] == pytest.approx(2.0)
    v_before = E.summary_table(st, stock_px.iloc[1], etf_px.iloc[1], CFG)["total"]
    assert v_before == pytest.approx(800.0)
    # A doubles then halves with no renewal of tranche 0: the book is back where it started
    assert E.summary_table(st, stock_px.iloc[2], etf_px.iloc[2], CFG)["total"] == pytest.approx(1000.0)
    assert E.summary_table(st, stock_px.iloc[3], etf_px.iloc[3], CFG)["total"] == pytest.approx(800.0)


def test_zero_recommended_parks_the_tranche_no_fallback():
    st = E.new_state(800.0, str(DATES[0].date()), CFG)
    rk = _ranking(["A", "B", "C"], n=0)
    stock_px = _prices(["A", "B", "C"], [[10, 10, 10]])
    etf_px = _prices(["SPY"], [[100]])
    st, orders = E.plan(st, str(DATES[0].date()), rk, stock_px, etf_px, 0.0, CFG)
    assert not [o for o in orders if o["side"] == "buy"], "zero recommended must not buy anything"
    assert [o for o in orders if o["sleeve"] == "stocks" and o["side"] == "park"]


def test_all_vetoed_parks_too_and_buffer_keeps_a_held_name():
    st = E.new_state(800.0, str(DATES[0].date()), CFG)
    rk = _ranking(["A", "B"], n=2, vetoed=("A", "B"))
    st, orders = E.plan(st, str(DATES[0].date()), rk, _prices(["A", "B"], [[10, 10]]), _prices(["SPY"], [[1]]), 0.0, CFG)
    assert not [o for o in orders if o["side"] == "buy"]
    # buffer: held name ranked 3 of 4 (within 2n=4 with n=2) stays; a held name ranked 5 leaves
    names = E.select_tranche_names(_ranking(["A", "B", "C", "D", "E"], n=2), 2, held={"C"}, buffer=2.0)
    assert names == ["C", "A"]
    names = E.select_tranche_names(_ranking(["A", "B", "C", "D", "E"], n=2), 2, held={"E"}, buffer=2.0)
    assert names == ["A", "B"]
    # sector cap: three names in one sector, cap 2 -> third skipped, "Other" exempt
    sec = {"A": "Tech", "B": "Tech", "C": "Tech", "D": "Other"}
    assert E.select_tranche_names(_ranking(["A", "B", "C", "D"], n=3, sectors=sec), 3, set(), 1.0, max_per_sector=2) == ["A", "B", "D"]


def test_plan_is_idempotent_and_refuses_to_plan_over_pending():
    st = E.new_state(800.0, str(DATES[0].date()), CFG)
    px = _prices(["A"], [[10], [10]]); epx = _prices(["SPY"], [[1], [1]])      # two bars: anchor + next
    st, o1 = E.plan(st, str(DATES[0].date()), _ranking(["A"]), px.iloc[:1], epx.iloc[:1], 0.0, CFG)
    with pytest.raises(RuntimeError):
        E.plan(st, str(DATES[1].date()), _ranking(["A"]), px, epx, 0.0, CFG)   # pending not settled
    E.settle(st, str(DATES[1].date()), px.iloc[-1], epx.iloc[-1], CFG)
    st, o2 = E.plan(st, str(DATES[1].date()), _ranking(["A"]), px, epx, 0.0, CFG)   # week 1 -> tranche 1
    assert o2 and all(o["tranche"] == 1 for o in o2)
    st, o3 = E.plan(st, str(DATES[1].date()), _ranking(["A"]), px, epx, 0.0, CFG)   # same day again
    assert o3 == []
    assert E.renewal_slot(st, DATES, str(DATES[1].date()), CFG) is None


def test_reset_transfer_moves_cash_from_the_richer_sleeve():
    st = E.new_state(800.0, str(DATES[0].date()), CFG)
    # force an imbalance: stocks sleeve worth 600 (tranche 0 has 400 cash), etf sleeve 200
    st["sleeves"]["stocks"]["tranches"][0]["cash"] = 400.0
    st["sleeves"]["etf"]["tranches"][0]["cash"] = 0.0
    px = _prices(["A"], [[10]]); epx = _prices(["SPY"], [[1]])
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(["A"], n=0), px, epx, 0.0, CFG)
    tr = {(o["sleeve"], o["side"]): o["dollars"] for o in orders if o["side"].startswith("transfer")}
    assert tr[("stocks", "transfer_out")] == pytest.approx(400 - 800 / 4)      # renewed tranche sized to 1/4 (2 tranches)
    assert tr[("etf", "transfer_in")] == pytest.approx(800 / 4 - 0.0)
    E.settle(st, str(DATES[1].date()), px.iloc[-1], epx.iloc[-1], CFG)
    s = E.summary_table(st, px.iloc[-1], epx.iloc[-1], CFG)
    assert s["sleeves"]["stocks"]["value"] == pytest.approx(400.0) and s["sleeves"]["etf"]["value"] == pytest.approx(400.0)


def test_reset_legs_offset_and_the_book_is_conserved_when_tranches_have_drifted():
    """TASK-347 review: sizing each renewed tranche to 1/8 of the whole book made the two transfer
    legs unequal whenever the renewed pair was not worth 1/4 of the book -> cash appeared or vanished
    on paper (-0.9 pp/yr in-sample). The pair is now split equally by its own value."""
    st = E.new_state(800.0, str(DATES[0].date()), CFG)
    st["sleeves"]["stocks"]["tranches"][0]["cash"] = 350.0; st["sleeves"]["stocks"]["tranches"][1]["cash"] = 50.0
    st["sleeves"]["etf"]["tranches"][0]["cash"] = 250.0; st["sleeves"]["etf"]["tranches"][1]["cash"] = 150.0
    px = _prices(["A"], [[10], [10]]); epx = _prices(["SPY"], [[1], [1]])
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(["A"], n=0), px.iloc[:1], epx.iloc[:1], 0.0, CFG)
    legs = {o["sleeve"]: (o["side"], o["dollars"]) for o in orders if o["side"].startswith("transfer")}
    assert legs["stocks"] == ("transfer_out", pytest.approx(50.0))       # pair worth 600 -> 300 each
    assert legs["etf"] == ("transfer_in", pytest.approx(50.0))
    E.settle(st, str(DATES[1].date()), px.iloc[1], epx.iloc[1], CFG)
    s = E.summary_table(st, px.iloc[1], epx.iloc[1], CFG)
    assert s["total"] == pytest.approx(800.0)                             # nothing created or destroyed
    assert st["sleeves"]["stocks"]["tranches"][0]["cash"] == pytest.approx(300.0)
    assert st["sleeves"]["etf"]["tranches"][0]["cash"] == pytest.approx(300.0)
    assert sum(t["dollars"] for t in st["transfers"]) == pytest.approx(0.0)


def test_etf_hurdle_uses_the_trailing_tbill_history_not_the_last_print():
    """The lab's ETF signal is mom12 minus the accumulated 252-bar T-bill return. Rates at 0% for
    ten months then 8%: trailing hurdle ~1.7% (SPY at +4.5% is ON); a flat 8% would switch it OFF."""
    n = 260
    dates = pd.bdate_range("2025-01-02", periods=n)
    spy = pd.DataFrame({"SPY": np.linspace(100.0, 104.5, n)}, index=dates)
    stock_px = pd.DataFrame({"A": np.full(n, 10.0)}, index=dates)
    tb = pd.Series(np.where(np.arange(n) < 207, 0.0, 0.08), index=dates)
    cfg = dict(CFG, step_bars=5, hold_bars=10)
    today = str(dates[-1].date())
    st_series = E.new_state(800.0, today, cfg)
    st_series, o_series = E.plan(st_series, today, _ranking(["A"], n=0), stock_px, spy, tb, cfg)
    assert [o for o in o_series if o["sleeve"] == "etf" and o["side"] == "buy"], "trailing hurdle 1.7% < 4.5%: SPY on"
    st_flat = E.new_state(800.0, today, cfg)
    st_flat, o_flat = E.plan(st_flat, today, _ranking(["A"], n=0), stock_px, spy, 0.08, cfg)
    assert not [o for o in o_flat if o["sleeve"] == "etf" and o["side"] == "buy"], "flat 8% > 4.5%: SPY off"
    assert [o for o in o_flat if o["sleeve"] == "etf" and o["side"] == "park"]


def test_idle_cash_accrues_the_tbill_between_runs_and_is_recorded():
    """Lucas 2026-09-05: the books model the money-market yield. 800 cash, 2.52% flat, one bar
    between runs -> +0.08 (800 * 0.0252/252); nothing on the first run; recorded per sleeve."""
    st = E.new_state(800.0, str(DATES[0].date()), CFG)
    px = _prices(["A"], [[10], [10], [10]]); epx = _prices(["SPY"], [[1], [1], [1]])
    st, _ = E.plan(st, str(DATES[0].date()), _ranking(["A"], n=0), px.iloc[:1], epx.iloc[:1], 0.0252, CFG)
    assert st["interest"] == [] and E.summary_table(st, px.iloc[0], epx.iloc[0], CFG)["total"] == pytest.approx(800.0)
    E.settle(st, str(DATES[1].date()), px.iloc[1], epx.iloc[1], CFG)          # only park orders: all still cash
    st, _ = E.plan(st, str(DATES[1].date()), _ranking(["A"], n=0), px.iloc[:2], epx.iloc[:2], 0.0252, CFG)
    assert E.summary_table(st, px.iloc[1], epx.iloc[1], CFG)["total"] == pytest.approx(800.0 + 800.0 * 0.0252 / 252)
    assert sum(r["dollars"] for r in st["interest"]) == pytest.approx(800.0 * 0.0252 / 252)
    assert {r["sleeve"] for r in st["interest"]} == {"stocks", "etf"} and all(r["bars"] == 1 for r in st["interest"])
    # a Series uses the print of each bar: 0% on the first bar, 5.04% on the next -> one bar at 5.04%
    tb = pd.Series([0.0, 0.0, 0.0504], index=DATES[:3])
    E.settle(st, str(DATES[2].date()), px.iloc[2], epx.iloc[2], CFG)
    before = E.summary_table(st, px.iloc[2], epx.iloc[2], CFG)["total"]
    st, _ = E.plan(st, str(DATES[2].date()), _ranking(["A"], n=0), px, epx, tb, CFG)
    assert E.summary_table(st, px.iloc[2], epx.iloc[2], CFG)["total"] == pytest.approx(before * (1 + 0.0504 / 252))


def test_stale_counter_survives_the_state_and_a_delisted_name_is_written_off():
    """TASK-350 review: `_book()` rebuilt tranches without `stale`, so a name that stopped printing
    was carried at its last price forever. Buy A, then A never prints again: after `max_stale_bars`
    marks it must be written off at its last price (recorded), with the state round-tripped through
    JSON between marks as production does."""
    import json as _json
    cfg = dict(CFG, max_stale_bars=3, step_bars=1, hold_bars=2)
    dates = pd.bdate_range("2026-01-05", periods=8)
    a = [10.0] + [np.nan] * 7                                         # prints once, then delists
    px = pd.DataFrame({"A": a, "B": [5.0] * 8}, index=dates); epx = pd.DataFrame({"SPY": [1.0] * 8}, index=dates)
    st = E.new_state(800.0, str(dates[0].date()), cfg)
    st, _ = E.plan(st, str(dates[0].date()), _ranking(["A"]), px.iloc[:1], epx.iloc[:1], 0.0, cfg)
    E.settle(st, str(dates[0].date()), px.iloc[0], epx.iloc[0], cfg)   # fill A at 10 (same-day print)
    assert st["sleeves"]["stocks"]["tranches"][0]["units"]["A"] == pytest.approx(20.0)
    for i in range(1, 5):                                              # four weekly marks without a print
        st = _json.loads(_json.dumps(st))                              # production round-trip
        st, _ = E.plan(st, str(dates[i].date()), _ranking(["B"], n=0), px.iloc[:i + 1], epx.iloc[:i + 1], 0.0, cfg)
        E.settle(st, str(dates[i].date()), px.iloc[i], epx.iloc[i], cfg)
        if i < 3:
            assert st["sleeves"]["stocks"]["tranches"][0]["stale"]["A"] == i
    assert "A" not in st["sleeves"]["stocks"]["tranches"][0]["units"]
    assert st["write_offs"] and st["write_offs"][0]["ticker"] == "A"
    assert st["write_offs"][0]["proceeds"] == pytest.approx(200.0)      # 20 units at the last price 10
    assert E.summary_table(st, px.iloc[4], epx.iloc[4], cfg)["total"] == pytest.approx(800.0)


def test_a_name_that_leaves_the_tranche_is_sold_to_zero_units_not_dust():
    """TASK-350 review: a dollar-sized sell settled at a higher t+1 price left 1e-10 units behind,
    which later showed up as hold_no_price and write-offs. A close-out sells every unit."""
    st = E.new_state(800.0, str(DATES[0].date()), CFG)
    px = _prices(["A", "B"], [[10, 10], [10, 10], [11, 10]]); epx = _prices(["SPY"], [[1], [1], [1]])
    st, _ = E.plan(st, str(DATES[0].date()), _ranking(["A"]), px.iloc[:1], epx.iloc[:1], 0.0, CFG)
    E.settle(st, str(DATES[1].date()), px.iloc[1], epx.iloc[1], CFG)        # tranche 0 holds A
    st, _ = E.plan(st, str(DATES[1].date()), _ranking(["B"]), px.iloc[:2], epx.iloc[:2], 0.0, CFG)   # week 1 -> tranche 1
    E.settle(st, str(DATES[2].date()), px.iloc[2], epx.iloc[2], CFG)
    # tranche 0 renews at DATES[2] with B only: A must leave completely although A is now 11, not 10
    st, orders = E.plan(st, str(DATES[2].date()), _ranking(["B"]), px, epx, 0.0, dict(CFG, step_bars=1))
    sell = next(o for o in orders if o["side"] == "sell" and o["ticker"] == "A")
    assert sell["close"] is True
    px3 = pd.Series({"A": 12.0, "B": 10.0}); epx3 = pd.Series({"SPY": 1.0})
    fills = E.settle(st, "2026-01-08", px3, epx3, CFG)
    f = next(x for x in fills if x["ticker"] == "A")
    assert f["units"] == pytest.approx(20.0) and f["dollars"] == pytest.approx(240.0)   # all 20 units at 12
    assert "A" not in st["sleeves"]["stocks"]["tranches"][0]["units"]


def test_costs_and_unfilled_orders_are_recorded():
    cfg = dict(CFG, stock_cost_bp=10.0)
    st = E.new_state(800.0, str(DATES[0].date()), cfg)
    px = _prices(["A", "B"], [[10, 10], [10, np.nan]]); epx = _prices(["SPY"], [[1], [1]])
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(["A", "B"]), px.iloc[:1], epx.iloc[:1], 0.0, cfg)
    fills = E.settle(st, str(DATES[1].date()), px.iloc[1], epx.iloc[1], cfg)
    a = next(f for f in fills if f["ticker"] == "A"); b = next(f for f in fills if f["ticker"] == "B")
    assert a["status"] == "filled" and a["cost"] == pytest.approx(a["dollars"] * 0.001)
    assert b["status"] == "not_filled"                          # no price on execution day: nothing invented
    assert st["ledger"] and st["pending"] == []


# ----------------------------------------------------------------------------- parity with the lab
LAB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "experiments")


def _lab():
    if not os.path.exists(os.path.join(LAB, "_sweep_cache", "close.pkl")):
        pytest.skip("lab cache experiments/_sweep_cache/ not present")
    sys.path.insert(0, LAB)
    import redesign_lab as L
    return L


def test_parity_stock_targets_with_redesign_lab():
    L = _lab()
    P = L.load_panel(oos=False)
    cfg = L.CONFIGS["T20"]; c = dict(L.BASE); c.update(cfg)
    checked = 0
    held = set()
    for t in range(1300, len(P.close.index) - 6, 5):
        out = L.rank_day(P, t, c)
        if out is None:
            continue
        m = P.meta_for(t, True)
        n = max(6, min(int(round(14 * m.overall_aggression * m.pillar_multipliers["COMPASS"])), 28))
        sel = L.select(out, n, held, c["buffer"])
        basket = P.rets.iloc[t - 62:t + 1][sel.index].mean(axis=1)
        rv = float(basket.std(ddof=1)) * np.sqrt(252)
        expo = min(1.0, c["target_vol"] / rv) if rv > 0 else 1.0
        lab_w = pd.Series(expo / len(sel), index=sel.index) if len(sel) else pd.Series(dtype=float)
        # production-shaped ranking from the same frame: rank order, sector, veto as a "Vetado" reason
        rk = pd.DataFrame({"ticker": out.index, "rank": range(1, len(out) + 1), "sector": out["sector"].values,
                           "reason": np.where(L.vetoed(out).values, "Vetado: gate", ""), "recommended_count": n})
        eng_w = E.stock_targets(rk, held, P.close.iloc[:t + 1], dict(V9, stock_buffer=c["buffer"], stock_target_vol=c["target_vol"]))
        pd.testing.assert_series_equal(eng_w.sort_index(), lab_w.sort_index(), check_names=False, rtol=0, atol=1e-9)
        held = set(sel.index)
        checked += 1
        if checked >= 25:
            break
    assert checked >= 20


def test_parity_etf_targets_with_sleeve_lab():
    L = _lab()
    import sleeve_lab as S
    from sleeves.etf_trend import target_weights
    P = L.load_panel(oos=False)
    P.ETF = S.load_etfs(P.close.index)
    tb_daily = P.IRX / 252.0
    px = P.ETF; rets = px.pct_change(fill_method=None); vol63 = rets.rolling(63).std() * np.sqrt(252)
    tb12 = tb_daily.rolling(252).sum(); mom12 = px / px.shift(252) - 1
    checked = 0
    for t in range(1300, len(px.index) - 6, 5):
        names = px.columns[(px.iloc[t].notna() & px.iloc[t - 252].notna()).values]
        on = mom12.iloc[t][names] - tb12.iloc[t] > 0
        iv = (1.0 / vol63.iloc[t][names]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        base = iv / iv.sum()
        lab_w = (base * on.astype(float)); lab_w = lab_w[lab_w > 0]
        eng_w = target_weights(px.iloc[:t + 1], tb_daily.iloc[:t + 1])
        pd.testing.assert_series_equal(eng_w.sort_index(), lab_w.sort_index(), check_names=False, rtol=0, atol=1e-9)
        checked += 1
        if checked >= 25:
            break
    assert checked >= 20
