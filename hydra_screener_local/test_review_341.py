"""TASK-341 independent review of core/portfolio_engine.py (commit 62598ab).

Review, do not re-implement. Parity is reproduced against the lab cache when present.
Counterexamples below: a pass means the engine holds, a fail is a finding.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import V9  # noqa: E402
import core.portfolio_engine as E  # noqa: E402

CFG = dict(V9, tranches=2, step_bars=1, hold_bars=2, stock_cost_bp=0.0, etf_cost_bp=0.0)
DATES = pd.bdate_range("2026-01-05", periods=10)


def _ranking(names, n=None, sectors=None, vetoed=()):
    n = len(names) if n is None else n
    return pd.DataFrame({
        "ticker": names, "rank": range(1, len(names) + 1),
        "sector": [sectors.get(t, "Other") if sectors else "Other" for t in names],
        "recommended": [i < n for i in range(len(names))],
        "reason": ["Vetado: caída reciente" if t in vetoed else "" for t in names],
        "recommended_count": n,
    })


def _prices(cols, rows):
    return pd.DataFrame(rows, index=DATES[: len(rows)], columns=cols, dtype=float)


def test_zero_recommended_parks_to_tbill_never_buys():
    st = E.new_state(800.0, str(DATES[0].date()), CFG)
    rk = _ranking(["A", "B", "C"], n=0)
    px = _prices(["A", "B", "C"], [[10, 10, 10]])
    epx = _prices(["SPY"], [[100]])
    st, orders = E.plan(st, str(DATES[0].date()), rk, px, epx, 0.0, CFG)
    assert not [o for o in orders if o["side"] == "buy"]
    assert [o for o in orders if o["sleeve"] == "stocks" and o["side"] == "park"]


def test_all_etfs_off_parks_the_etf_tranche():
    """Short ETF history -> not eligible -> empty targets -> park, no buy."""
    st = E.new_state(800.0, str(DATES[0].date()), CFG)
    px = _prices(["A"], [[10]])
    epx = _prices(["SPY"], [[100]])          # << 252 bars
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(["A"]), px, epx, 0.0, CFG)
    assert [o for o in orders if o["sleeve"] == "etf" and o["side"] == "park"]
    assert not [o for o in orders if o["sleeve"] == "etf" and o["side"] == "buy"]


def test_missing_price_on_execution_day_does_not_invent_a_fill():
    cfg = dict(CFG, stock_cost_bp=10.0)
    st = E.new_state(800.0, str(DATES[0].date()), cfg)
    px = _prices(["A", "B"], [[10, 10], [10, np.nan]])
    epx = _prices(["SPY"], [[1], [1]])
    st, _ = E.plan(st, str(DATES[0].date()), _ranking(["A", "B"]), px.iloc[:1], epx.iloc[:1], 0.0, cfg)
    fills = E.settle(st, str(DATES[1].date()), px.iloc[1], epx.iloc[1], cfg)
    b = next(f for f in fills if f["ticker"] == "B")
    assert b["status"] == "not_filled"
    assert "B" not in st["sleeves"]["stocks"]["tranches"][0]["units"]


def test_reset_when_one_sleeve_doubled_moves_cash_not_shares():
    st = E.new_state(800.0, str(DATES[0].date()), CFG)
    # conserve the book: stocks sleeve 600, etf sleeve 200 (was 400/400)
    st["sleeves"]["stocks"]["tranches"][0]["cash"] = 400.0
    st["sleeves"]["etf"]["tranches"][0]["cash"] = 0.0
    px = _prices(["A"], [[10]])
    epx = _prices(["SPY"], [[1]])
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(["A"], n=0), px, epx, 0.0, CFG)
    tr = {(o["sleeve"], o["side"]): o["dollars"] for o in orders if str(o["side"]).startswith("transfer")}
    assert ("stocks", "transfer_out") in tr and ("etf", "transfer_in") in tr
    assert tr[("stocks", "transfer_out")] == pytest.approx(tr[("etf", "transfer_in")])


def test_plan_twice_on_the_same_date_emits_nothing():
    st = E.new_state(800.0, str(DATES[0].date()), CFG)
    px = _prices(["A"], [[10], [10]])
    epx = _prices(["SPY"], [[1], [1]])
    st, o1 = E.plan(st, str(DATES[0].date()), _ranking(["A"]), px.iloc[:1], epx.iloc[:1], 0.0, CFG)
    E.settle(st, str(DATES[1].date()), px.iloc[-1], epx.iloc[-1], CFG)
    st, o2 = E.plan(st, str(DATES[1].date()), _ranking(["A"]), px, epx, 0.0, CFG)
    st, o3 = E.plan(st, str(DATES[1].date()), _ranking(["A"]), px, epx, 0.0, CFG)
    assert o2 and o3 == []


def test_capital_reference_change_mid_life_does_not_silently_resize():
    """Lucas changing capital_reference in the JSON must not rescale units.

    Sizing uses the marked book, not the reference. A change of the reference
    without a matching cash deposit leaves the book as-is (and should not
    invent shares). If the engine *did* scale to the new reference, that would
    be a silent rewrite of the live book.
    """
    st = E.new_state(800.0, str(DATES[0].date()), CFG)
    px = _prices(["A"], [[10], [10]])
    epx = _prices(["SPY"], [[1], [1]])
    st, _ = E.plan(st, str(DATES[0].date()), _ranking(["A"]), px.iloc[:1], epx.iloc[:1], 0.0, CFG)
    E.settle(st, str(DATES[1].date()), px.iloc[-1], epx.iloc[-1], CFG)
    units_before = dict(st["sleeves"]["stocks"]["tranches"][0]["units"])
    cash_before = st["sleeves"]["stocks"]["tranches"][0]["cash"]
    st["capital_reference"] = 8_000_000.0
    st, orders = E.plan(st, str(DATES[1].date()), _ranking(["A"]), px, epx, 0.0, CFG)
    # week 1 renews the *other* tranche; tranche 0 units must not have been scaled
    assert st["sleeves"]["stocks"]["tranches"][0]["units"] == units_before
    assert st["sleeves"]["stocks"]["tranches"][0]["cash"] == pytest.approx(cash_before)
    assert st["capital_reference"] == 8_000_000.0


def test_park_and_hold_no_price_survive_settle_into_the_ledger():
    """park / hold_no_price are real instruction sides. settle() only loops
    sell/transfer/buy, then wipes pending — those sides would vanish unrecorded."""
    st = E.new_state(800.0, str(DATES[0].date()), CFG)
    px = _prices(["A"], [[10], [10]])
    epx = _prices(["SPY"], [[1], [1]])
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(["A"], n=0), px.iloc[:1], epx.iloc[:1], 0.0, CFG)
    parks = [o for o in orders if o["side"] == "park"]
    assert parks, "zero-recommended must emit park"
    fills = E.settle(st, str(DATES[1].date()), px.iloc[1], epx.iloc[1], CFG)
    recorded = [x["side"] for x in fills] + [x.get("side") for x in st["ledger"]]
    assert "park" in recorded, (
        f"park orders were dropped on settle (fills={ [f.get('side') for f in fills] }); "
        "the instruction never lands in the ledger"
    )


def test_parity_stock_targets_reproduced():
    lab = os.path.join(os.path.dirname(os.path.abspath(__file__)), "experiments")
    if not os.path.exists(os.path.join(lab, "_sweep_cache", "close.pkl")):
        pytest.skip("lab cache experiments/_sweep_cache/ not present")
    sys.path.insert(0, lab)
    import redesign_lab as L
    P = L.load_panel(oos=False)
    cfg = L.CONFIGS["T20"]
    c = dict(L.BASE)
    c.update(cfg)
    checked, held = 0, set()
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
        rk = pd.DataFrame({
            "ticker": out.index, "rank": range(1, len(out) + 1),
            "sector": out["sector"].values,
            "reason": np.where(L.vetoed(out).values, "Vetado: gate", ""),
            "recommended_count": n,
        })
        eng_w = E.stock_targets(
            rk, held, P.close.iloc[: t + 1],
            dict(V9, stock_buffer=c["buffer"], stock_target_vol=c["target_vol"]),
        )
        pd.testing.assert_series_equal(eng_w.sort_index(), lab_w.sort_index(),
                                       check_names=False, rtol=0, atol=1e-9)
        held = set(sel.index)
        checked += 1
        if checked >= 20:
            break
    assert checked >= 20
