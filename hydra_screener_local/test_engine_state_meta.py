"""ASTRA-09 — the invariants the N-sleeve / hardening merge must satisfy.

The external audit (Astra, 2026-09-06) found that the two open branches each keep a guarantee the
other drops, and that one of them is about the book's exposure:

  * the integration side validates and persists a ``mix``, but ``plan()`` sizes a renewed tranche as
    ``sum(own) / 2`` and iterates a hard-coded pair of sleeves. On an 8000 USD book already balanced
    to 80/20 the renewed bundle owns 1600 (stocks) + 400 (etf) = 2000, the halving rule targets
    1000 each, and the engine emits a spurious 600 USD transfer between tranches.
  * this side (``n-sleeve-engine``) reads the mix from the registry and iterates N sleeves, so the
    80/20 book is quiet and three sleeves conserve capital — but ``new_state()`` carries none of the
    metadata the hardening work persists (config, mix, sleeve registry, calendar), ``renewal_slot()``
    still counts whatever index the last download returned, and the mix guards accept NaN and
    negative weights.

Astra's probe ``test_engine_respects_saved_nondefault_mix_on_renewal`` passes on ``main`` and fails
against the integration branch: the defect appears at merge time, which is why it needs a test.

Nothing here edits the engine. Every test is either an invariant that holds on this branch and must
keep holding after the merge, or an ``xfail(strict=True)`` that names exactly what the merge still
owes — a strict xfail turns into a failure the day it starts passing, so the marker cannot outlive
the fix. No network, no ``state/``, no ``data_cache/``: synthetic frames only.
"""
from __future__ import annotations

import copy
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import V9  # noqa: E402
import core.portfolio_engine as E  # noqa: E402
from core.state_check import check  # noqa: E402
from sleeves.registry import build  # noqa: E402

STOCKS = ["AAA", "BBB", "CCC"]
ETFS = list(V9["etf_universe"])
DATES = pd.bdate_range("2026-01-05", periods=60)

# three sleeves: the stock sleeve plus two independent ETF-trend instances with their own cost
CFG3 = {**V9, "sleeves": ["stocks", "etf", {"name": "etf_slow", "type": "etf", "cost_bp": 3.0}],
        "mix": {"stocks": 0.5, "etf": 0.3, "etf_slow": 0.2},
        "etf_lookback_bars": 20, "etf_vol_bars": 10}
FREE = {"stock_cost_bp": 0.0, "etf_cost_bp": 0.0}     # cost-free variants isolate conservation


# --------------------------------------------------------------------------------------- fixtures
def _stock_frame(n: int = 30, level: float = 100.0, names=None) -> pd.DataFrame:
    names = list(names or STOCKS)
    return pd.DataFrame({t: [level] * n for t in names}, index=DATES[:n], dtype=float)


def _etf_frame(n: int = 30, level: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame({t: [level] * n for t in ETFS}, index=DATES[:n], dtype=float)


def _drifting_frames(n: int = 40, seed: int = 9):
    """Frames that actually move, so the ETF trend sleeve picks names and real trades happen."""
    rng = np.random.default_rng(seed)
    stock = 100.0 * np.cumprod(1 + rng.normal(0.0008, 0.010, size=(n, len(STOCKS))), axis=0)
    etf = 100.0 * np.cumprod(1 + rng.normal(0.0010, 0.006, size=(n, len(ETFS))), axis=0)
    return (pd.DataFrame(stock, index=DATES[:n], columns=STOCKS),
            pd.DataFrame(etf, index=DATES[:n], columns=ETFS))


def _ranking(names=None, n: int | None = None) -> pd.DataFrame:
    names = list(names if names is not None else STOCKS)
    n = len(names) if n is None else n
    return pd.DataFrame({"ticker": names, "rank": range(1, len(names) + 1),
                         "sector": ["Other"] * len(names), "reason": [""] * len(names),
                         "recommended": [i < n for i in range(len(names))],
                         "recommended_count": n})


def _book_value(state: dict, px_s: pd.Series, px_e: pd.Series, cfg: dict) -> float:
    """Cash + units x price read straight out of the state dict.

    Deliberately independent of ``mark`` / ``summary_table``: an oracle that shares code with the
    thing it measures cannot catch capital going missing. A sleeve the cfg does not know is valued
    on the stock row (the fallback the engine itself would have to choose).
    """
    try:
        rows = E._price_rows(E._sleeves(cfg), px_s, px_e)
    except (KeyError, ValueError, TypeError):
        rows = {}
    total = 0.0
    for name, book in (state.get("sleeves") or {}).items():
        px = rows.get(name, px_s)
        for tr in book["tranches"]:
            total += float(tr["cash"])
            for tk, u in (tr.get("units") or {}).items():
                p = px.get(tk, (tr.get("last_px") or {}).get(tk, 0.0))
                p = float(p) if p is not None and float(p) == float(p) else 0.0
                total += float(u) * p
    return total


def _legs(orders: list) -> dict:
    """sleeve -> signed transfer dollars."""
    return {o["sleeve"]: (o["dollars"] if o["side"] == "transfer_in" else -o["dollars"])
            for o in orders if o["side"] in ("transfer_in", "transfer_out")}


# =============================================================== 1. the mix and the transfer legs
def test_a_book_already_at_its_target_mix_emits_no_transfer():
    """Astra's probe, assertion preserved: an 8000 USD book opened at 80/20 must be quiet.

    ``new_state`` funds stocks with 8000 x 0.8 / 4 = 1600 per tranche and etf with 400, so the
    renewed bundle is worth 2000 and the 80/20 split of it is exactly what each sleeve already
    owns. The ``sum(own) / 2`` rule would target 1000 apiece and move 600 USD.
    """
    cfg = copy.deepcopy(V9)
    cfg["mix"] = {"stocks": 0.8, "etf": 0.2}
    idx = pd.bdate_range("2025-01-01", periods=300)
    prices = pd.DataFrame({"AAA": 100.0}, index=idx)
    etf = pd.DataFrame({x: 100.0 for x in cfg["etf_universe"]}, index=idx)
    date = str(idx[-1].date())
    s = E.new_state(8000, date, cfg)
    ranking = pd.DataFrame({"ticker": ["AAA"], "rank": [1], "recommended_count": [0],
                            "recommended": [False]})
    s, orders = E.plan(s, date, ranking, prices, etf, 0.0, cfg)
    transfers = [o for o in orders if o["side"].startswith("transfer_")]
    assert not transfers, transfers
    # and the money that stayed put is the money the halving rule would have moved
    parks = {o["sleeve"]: o["dollars"] for o in orders if o["side"] == "park"}
    assert parks == pytest.approx({"stocks": 1600.0, "etf": 400.0})
    assert 600.0 not in [round(o["dollars"], 6) for o in orders]


@pytest.mark.parametrize("mix", [
    {"stocks": 0.5, "etf": 0.5},
    {"stocks": 0.8, "etf": 0.2},
    {"stocks": 0.2, "etf": 0.8},
    {"stocks": 0.65, "etf": 0.35},
    {"stocks": 0.9, "etf": 0.1},
])
def test_no_mix_that_the_book_already_holds_produces_a_transfer(mix):
    """The 50/50 case is production; the others are the ones the merge must not disturb."""
    cfg = {**V9, "mix": mix}
    n = 30
    st = E.new_state(8000.0, str(DATES[0].date()), cfg)
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(n=0),
                        _stock_frame(n), _etf_frame(n), 0.0, cfg)
    assert _legs(orders) == {}, orders
    parks = {o["sleeve"]: o["dollars"] for o in orders if o["side"] == "park"}
    assert parks == pytest.approx({s: 8000.0 * w / cfg["tranches"] for s, w in mix.items()})


def test_the_transfer_is_sized_off_the_renewed_bundle_not_off_the_whole_book():
    """The regression assertion for ``mix x book / (N x K)``.

    Tranche 0 is hand-set to 3000 (stocks) + 1000 (etf) = 4000 while the book is 8000, so the
    bundle is not 1/K of the book. Off the bundle the 80/20 targets are 3200 / 800 and the legs are
    +200 / -200, which net to zero. Off the whole book they would be 1600 / 400: legs of -1400 and
    -600 that destroy 2000 USD of cash on paper.
    """
    cfg = {**V9, "mix": {"stocks": 0.8, "etf": 0.2}}
    st = E.new_state(8000.0, str(DATES[0].date()), cfg)
    st["sleeves"]["stocks"]["tranches"][0]["cash"] = 3000.0
    st["sleeves"]["etf"]["tranches"][0]["cash"] = 1000.0
    for i in (1, 2, 3):                                   # keep the rest of the book at 8000 total
        st["sleeves"]["stocks"]["tranches"][i]["cash"] = 800.0
        st["sleeves"]["etf"]["tranches"][i]["cash"] = 200.0
    n = 30
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(n=0),
                        _stock_frame(n), _etf_frame(n), 0.0, cfg)
    assert _legs(orders) == pytest.approx({"stocks": 200.0, "etf": -200.0})
    assert sum(_legs(orders).values()) == pytest.approx(0.0)
    parks = {o["sleeve"]: o["dollars"] for o in orders if o["side"] == "park"}
    assert parks == pytest.approx({"stocks": 3200.0, "etf": 800.0})
    assert sum(parks.values()) == pytest.approx(4000.0), "the bundle is conserved by the reset"


def test_three_sleeve_transfer_legs_net_to_zero():
    st = E.new_state(1000.0, str(DATES[0].date()), CFG3)
    for name, own in (("stocks", 70.0), ("etf", 40.0), ("etf_slow", 10.0)):
        st["sleeves"][name]["tranches"][0]["cash"] = own
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(n=0),
                        _stock_frame(30), _etf_frame(30), 0.0, CFG3)
    legs = _legs(orders)
    assert legs == pytest.approx({"stocks": -10.0, "etf": -4.0, "etf_slow": 14.0})
    assert sum(legs.values()) == pytest.approx(0.0)


# ================================================================ 2. capital conservation, N > 2
def test_three_sleeves_conserve_the_book_through_plan_settle_and_mark():
    """The book's value at the execution close is what it was, minus the fees the ledger reports.

    Measured with ``_book_value`` (an oracle that does not share code with ``mark``), through a
    renewal that actually trades: plan at t, settle at t+1, mark at t+1.
    """
    cfg = {**CFG3, **FREE}
    cfg["sleeves"] = ["stocks", "etf", {"name": "etf_slow", "type": "etf", "cost_bp": 0.0}]
    stock, etf = _drifting_frames(40)
    t, e = 30, 31
    st = E.new_state(1000.0, str(DATES[t].date()), cfg)
    st, orders = E.plan(st, str(DATES[t].date()), _ranking(), stock.iloc[:t + 1],
                        etf.iloc[:t + 1], 0.0, cfg)
    assert {o["sleeve"] for o in orders} == {"stocks", "etf", "etf_slow"}
    assert any(o["side"] == "buy" for o in orders), "the cycle must trade, not just park"

    before = _book_value(st, stock.iloc[e], etf.iloc[e], cfg)
    fills = E.settle(st, str(DATES[e].date()), stock.iloc[e], etf.iloc[e], cfg)
    after = _book_value(st, stock.iloc[e], etf.iloc[e], cfg)
    fees = sum(float(f.get("cost") or 0.0) for f in fills if f["status"] == "filled")
    assert fees == pytest.approx(0.0), "this cfg is cost-free by construction"
    assert after == pytest.approx(before, abs=1e-9), "the cash-free legs must conserve the book"
    assert sum(row["dollars"] for row in st["transfers"]) == pytest.approx(0.0, abs=1e-9)

    E.mark(st, stock.iloc[e], etf.iloc[e], cfg)
    assert _book_value(st, stock.iloc[e], etf.iloc[e], cfg) == pytest.approx(after, abs=1e-9)
    assert st["write_offs"] == []
    assert [f.level for f in check(json.loads(json.dumps(st)), cfg=cfg) if f.level == "ERROR"] == []


def test_costs_are_the_only_leak_when_three_sleeves_trade():
    """Same cycle with real costs: the shortfall equals the fees, to the cent and to 1e-9."""
    cfg = CFG3
    stock, etf = _drifting_frames(40)
    t, e = 30, 31
    st = E.new_state(1000.0, str(DATES[t].date()), cfg)
    st, _ = E.plan(st, str(DATES[t].date()), _ranking(), stock.iloc[:t + 1], etf.iloc[:t + 1], 0.0, cfg)
    before = _book_value(st, stock.iloc[e], etf.iloc[e], cfg)
    fills = E.settle(st, str(DATES[e].date()), stock.iloc[e], etf.iloc[e], cfg)
    after = _book_value(st, stock.iloc[e], etf.iloc[e], cfg)
    fees = sum(float(f.get("cost") or 0.0) for f in fills if f["status"] == "filled")
    assert fees > 0.0
    assert before - after == pytest.approx(fees, abs=1e-9)
    # each sleeve pays its own tariff, including the second ETF instance at 3 bp
    for f in fills:
        if f["status"] == "filled" and f["ticker"] not in ("CASH", "TBILL"):
            want = {"stocks": V9["stock_cost_bp"], "etf": V9["etf_cost_bp"], "etf_slow": 3.0}[f["sleeve"]]
            assert f["cost"] == pytest.approx(f["dollars"] * want / 1e4)


def test_every_week_of_a_three_sleeve_run_conserves_the_book_and_restores_the_mix():
    """The regression net: six consecutive renewals, not just the first one.

    Week 0 is the easy case — every tranche is still cash at exactly mix x capital / K, so a
    whole-book sizing rule and a bundle sizing rule agree. From week 1 the tranches hold different
    names at different prices and the two rules diverge; this walks six weeks of plan / settle /
    mark and asserts, every week, that (a) each sleeve's renewed tranche is aimed at exactly its
    share of the bundle those tranches own, measured at the plan close, and (b) settling loses
    exactly the fees the ledger reports.
    """
    cfg = CFG3
    stock, etf = _drifting_frames(60, seed=386)
    st = E.new_state(1000.0, str(DATES[25].date()), cfg)
    names = ["stocks", "etf", "etf_slow"]
    total_fees = 0.0
    for week in range(6):
        t = 25 + week * cfg["step_bars"]
        e = t + 1
        k = week % cfg["tranches"]
        # what the renewed tranches own at the plan close, before the engine touches them
        own = {}
        for name in names:
            tr = st["sleeves"][name]["tranches"][k]
            px = stock.iloc[t] if name == "stocks" else etf.iloc[t]
            own[name] = float(tr["cash"]) + sum(float(u) * float(px.get(tk, 0.0))
                                                for tk, u in tr["units"].items())
        bundle = sum(own.values())

        st, orders = E.plan(st, str(DATES[t].date()), _ranking(STOCKS[week % 3:] + STOCKS[:week % 3]),
                            stock.iloc[:t + 1], etf.iloc[:t + 1], 0.0, cfg)
        assert st["week_index"] == week
        assert {o["tranche"] for o in orders} == {k}
        legs = _legs(orders)
        assert sum(legs.values()) == pytest.approx(0.0, abs=1e-9), (week, legs)
        # the reset aims each sleeve at mix x bundle; a whole-book rule would aim it at
        # mix x book / K, which from week 1 on is a different number
        for name in names:
            aimed = own[name] + legs.get(name, 0.0)
            assert aimed == pytest.approx(cfg["mix"][name] * bundle, abs=1e-9), (week, name, own)

        before = _book_value(st, stock.iloc[e], etf.iloc[e], cfg)
        fills = E.settle(st, str(DATES[e].date()), stock.iloc[e], etf.iloc[e], cfg)
        after = _book_value(st, stock.iloc[e], etf.iloc[e], cfg)
        fees = sum(float(f.get("cost") or 0.0) for f in fills if f["status"] == "filled")
        total_fees += fees
        assert before - after == pytest.approx(fees, abs=1e-9), f"week {week} leaked"
        E.mark(st, stock.iloc[e], etf.iloc[e], cfg)
        assert [f.level for f in check(json.loads(json.dumps(st)), cfg=cfg) if f.level == "ERROR"] == []
    assert total_fees > 0.0
    assert st["write_offs"] == []
    assert sum(row["dollars"] for row in st["transfers"]) == pytest.approx(0.0, abs=1e-9)


def test_the_equal_weight_fallback_and_an_explicit_5050_are_the_same_engine():
    """Production's path: a cfg with no mix must plan exactly what mix={0.5, 0.5} plans.

    A merge that starts persisting or validating the mix must not fork these two.
    """
    n = 30
    stock, etf = _stock_frame(n), _etf_frame(n)
    no_mix = {k: v for k, v in V9.items() if k != "mix"}
    a = E.new_state(8000.0, str(DATES[0].date()), no_mix)
    b = E.new_state(8000.0, str(DATES[0].date()), V9)
    assert json.loads(json.dumps(a)) == json.loads(json.dumps(b))
    a, orders_a = E.plan(a, str(DATES[0].date()), _ranking(), stock, etf, 0.0, no_mix)
    b, orders_b = E.plan(b, str(DATES[0].date()), _ranking(), stock, etf, 0.0, V9)
    assert orders_a == orders_b
    E.settle(a, str(DATES[1].date()), stock.iloc[1], etf.iloc[1], no_mix)
    E.settle(b, str(DATES[1].date()), stock.iloc[1], etf.iloc[1], V9)
    assert json.loads(json.dumps(a)) == json.loads(json.dumps(b))


def test_a_third_sleeve_does_not_change_what_the_book_is_worth():
    """Adding a sleeve reallocates the book; it must not create or destroy any of it."""
    two = E.new_state(1000.0, str(DATES[0].date()), V9)
    three = E.new_state(1000.0, str(DATES[0].date()), CFG3)
    px_s, px_e = _stock_frame(1).iloc[0], _etf_frame(1).iloc[0]
    assert _book_value(two, px_s, px_e, V9) == pytest.approx(1000.0)
    assert _book_value(three, px_s, px_e, CFG3) == pytest.approx(1000.0)
    per_sleeve = {n: sum(tr["cash"] for tr in b["tranches"]) for n, b in three["sleeves"].items()}
    assert per_sleeve == pytest.approx({"stocks": 500.0, "etf": 300.0, "etf_slow": 200.0})


@pytest.mark.xfail(strict=True, reason=(
    "n-sleeve engine walks cfg['sleeves'], not state['sleeves']: a sleeve the book holds but the "
    "config no longer names is silently unvalued (1000 USD missing from summary_table's total in "
    "the probe below). The hardening side walks the state (sleeve_names, R-804). The merge must "
    "value everything the state holds; remove this marker when it does."))
def test_capital_held_in_the_state_is_never_hidden_by_the_config():
    st = E.new_state(100000.0, str(DATES[0].date()), V9)
    st["sleeves"]["bonds"] = {"tranches": [
        {"k": i, "opened": None, "units": {}, "cash": 250.0, "last_px": {}, "stale": {}}
        for i in range(V9["tranches"])]}
    px_s, px_e = _stock_frame(1).iloc[0], _etf_frame(1).iloc[0]
    summary = E.summary_table(st, px_s, px_e, V9)
    assert "bonds" in summary["sleeves"], "the extra sleeve must be valued"
    assert summary["sleeves"]["bonds"]["cash"] == pytest.approx(1000.0)
    assert summary["total"] == pytest.approx(101000.0)


@pytest.mark.xfail(strict=True, reason=(
    "summary_table computes 'share' in a loop over the module constant SLEEVES = ('stocks','etf'), "
    "so a third sleeve gets no share and the sheet's shares sum to 0.8. Not scoring and not "
    "exposure — a read-only valuation — but it is the instruction sheet Lucas trades from."))
def test_every_sleeve_in_the_book_gets_a_share_in_the_sheet():
    st = E.new_state(1000.0, str(DATES[0].date()), CFG3)
    summary = E.summary_table(st, _stock_frame(1).iloc[0], _etf_frame(1).iloc[0], CFG3)
    shares = {n: v.get("share") for n, v in summary["sleeves"].items()}
    assert None not in shares.values(), shares
    assert sum(shares.values()) == pytest.approx(1.0)


# ============================================================ 3. a replay must not read the world
@pytest.mark.xfail(strict=True, reason=(
    "n-sleeve new_state() persists none of the hardening metadata (config, config_sha256, mix, "
    "sleeve_registry, calendar, last_mark_date): a saved book cannot say which configuration "
    "produced it, so a replay cannot be reproducible. The merge must keep the hardening keys while "
    "keeping the registry-driven mix."))
def test_the_state_persists_the_metadata_a_replay_needs():
    st = E.new_state(100000.0, "2026-01-02", V9)
    for key in ("schema_version", "config", "mix", "sleeve_registry", "calendar"):
        assert key in st, key
    assert st["mix"] == {"stocks": 0.5, "etf": 0.5}
    assert st["config"]["step_bars"] == V9["step_bars"]


@pytest.mark.xfail(strict=True, reason=(
    "plan() falls back to the module-level V9 when no cfg is passed, and the state carries no "
    "config, so editing config.V9 between two runs silently rewrites the replay of a saved book. "
    "The merge must resolve the cfg from the state (hardening's effective_config)."))
def test_changing_the_global_config_does_not_change_a_replay_of_a_saved_state(monkeypatch):
    n = 30
    stock, etf = _stock_frame(n), _etf_frame(n)
    st0 = E.new_state(8000.0, str(DATES[0].date()), V9)
    saved = json.loads(json.dumps(st0))
    st_a, orders_a = E.plan(st0, str(DATES[0].date()), _ranking(n=0), stock, etf, 0.0)
    # someone edits config.V9 between the two runs (a new cadence and a new mix)
    monkeypatch.setattr(E, "V9", {**V9, "step_bars": 7, "mix": {"stocks": 0.8, "etf": 0.2}})
    st_b, orders_b = E.plan(json.loads(json.dumps(saved)), str(DATES[0].date()),
                            _ranking(n=0), stock, etf, 0.0)
    assert orders_b == orders_a
    assert json.loads(json.dumps(st_b)) == json.loads(json.dumps(st_a))


@pytest.mark.xfail(strict=True, reason=(
    "the exposure case of the same defect: a book saved at 80/20 replays under the global 50/50 "
    "mix and the engine moves real money between sleeves. Needs the persisted mix to win over the "
    "imported one; the mix itself is Lucas's call, the persistence is not."))
def test_a_saved_non_default_mix_is_not_overwritten_by_the_global_one(monkeypatch):
    n = 30
    cfg = {**V9, "mix": {"stocks": 0.8, "etf": 0.2}}
    st = E.new_state(8000.0, str(DATES[0].date()), cfg)
    st["mix"] = dict(cfg["mix"])                       # what the hardening side persists
    st["config"] = dict(cfg)
    monkeypatch.setattr(E, "V9", dict(V9))             # the process imported the 50/50 default
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(n=0), _stock_frame(n), _etf_frame(n), 0.0)
    assert _legs(orders) == {}, "an 80/20 book replayed under the default mix must not be rebalanced"


@pytest.mark.xfail(strict=True, reason=(
    "portfolio_v9.run() does `cfg = cfg or V9` BEFORE load_state() and then hands that cfg to every "
    "engine call, so persisting a config in the state does not by itself prove a stable replay: the "
    "CLI overrides it. The merge must load the state first and let the saved config win."))
def test_the_cli_replays_with_the_configuration_saved_in_the_book(tmp_path):
    import portfolio_v9 as V

    seen = {}

    class Recorder:
        def new_state(self, capital, anchor, cfg):
            return E.new_state(capital, anchor, cfg)

        def settle(self, state, exec_date, stock_row, etf_row, cfg):
            state["pending"] = []
            return []

        def plan(self, state, today, ranking, stock_prices, etf_prices, tbill_rate, cfg):
            seen["cfg"] = cfg
            state["last_run_date"] = today
            return state, []

        def summary_table(self, state, stock_row, etf_row, cfg):
            return {"total": 0.0, "sleeves": {}}

    idx = pd.DatetimeIndex(["2026-09-04"])

    def market(_u=None):
        return dict(prices=pd.DataFrame({"AAA": [10.0]}, index=idx),
                    volumes=pd.DataFrame({"AAA": [1e6]}, index=idx),
                    spy=pd.Series([400.0], index=idx),
                    etf=pd.DataFrame({t: [100.0] for t in ETFS}, index=idx),
                    irx=pd.Series([5.25], index=idx),
                    stock_report={}, etf_report={}, irx_report={})

    state = E.new_state(8000.0, "2026-09-04", V9)
    state["config"] = {**V9, "step_bars": 7}
    (tmp_path / "portfolio_v9.json").write_text(json.dumps(state), encoding="utf-8")
    V.run(tmp_path, fetch_fn=market, rank_fn=lambda *a: _ranking(["AAA"], 1),
          engine=Recorder(), silent=True)
    assert seen["cfg"]["step_bars"] == 7, "the CLI must not override the saved configuration"


@pytest.mark.xfail(strict=True, reason=(
    "R-801: bars_between() counts rows of whatever index it is handed, so a shorter download moves "
    "the schedule. Probed here: 700 bars -> 699 bars since the anchor, week 139, no renewal; the "
    "same day on a 500-bar slice -> 500 bars, week 100, tranche 0 renews. The hardening side "
    "persists the calendar (record_calendar / effective_calendar); this side does not carry it."))
def test_the_renewal_week_does_not_depend_on_the_download_length():
    full = pd.bdate_range("2023-01-02", periods=700)
    anchor, today = str(full[0].date()), str(full[-1].date())
    st = E.new_state(100000.0, anchor, V9)
    st["week_index"] = 39
    assert E.bars_between(full[-500:], anchor, today) == E.bars_between(full, anchor, today)
    assert E.renewal_slot(st, full[-500:], today, V9) == E.renewal_slot(st, full, today, V9)


# ========================================================================== 4. guards still reject
def test_the_mix_guards_that_reject_today_still_reject():
    with pytest.raises(ValueError, match="sums to"):
        E.new_state(1000.0, "2026-01-05", {**V9, "mix": {"stocks": 0.5, "etf": 0.4}})
    with pytest.raises(ValueError, match="no weight"):
        E.new_state(1000.0, "2026-01-05", {**CFG3, "mix": {"stocks": 0.7, "etf": 0.3}})
    with pytest.raises(ValueError, match="sums to"):
        E._mix({**V9, "mix": {"stocks": 0.5, "etf": 0.4, "crypto": 0.1}}, ["stocks", "etf"])
    # an infinite weight already fails the sum check (nan does not; see the xfail below)
    with pytest.raises(ValueError, match="sums to"):
        E.new_state(1000.0, "2026-01-05", {**V9, "mix": {"stocks": float("inf"), "etf": 0.5}})
    # an absent mix is the documented equal-weight fallback, not an error
    assert E._mix({**V9, "mix": None}, ["stocks", "etf"]) == {"stocks": 0.5, "etf": 0.5}
    third = 1.0 / 3.0
    assert E._mix({"mix": {"a": third, "b": third, "c": third}}, ["a", "b", "c"]) == pytest.approx(
        {"a": third, "b": third, "c": third})


def test_the_registry_guards_that_reject_today_still_reject():
    with pytest.raises(KeyError, match="unknown sleeve"):
        build({**V9, "sleeves": ["momentum_reversal"]})
    with pytest.raises(ValueError, match="duplicate"):
        build({**V9, "sleeves": ["etf", "etf"]})
    with pytest.raises(TypeError):
        build({**V9, "sleeves": [42]})


def test_planning_over_unsettled_orders_still_raises():
    n = 30
    st = E.new_state(1000.0, str(DATES[0].date()), V9)
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(n=0), _stock_frame(n), _etf_frame(n), 0.0, V9)
    assert orders and st["pending"]
    with pytest.raises(RuntimeError, match="not settled"):
        E.plan(st, str(DATES[5].date()), _ranking(n=0), _stock_frame(n), _etf_frame(n), 0.0, V9)
    # and the same day twice is still a no-op, not a second set of orders
    st2 = E.new_state(1000.0, str(DATES[0].date()), V9)
    st2, first = E.plan(st2, str(DATES[0].date()), _ranking(n=0), _stock_frame(n), _etf_frame(n), 0.0, V9)
    st2, again = E.plan(st2, str(DATES[0].date()), _ranking(n=0), _stock_frame(n), _etf_frame(n), 0.0, V9)
    assert first and again == []


def test_a_name_without_a_print_is_carried_not_sold_and_not_filled():
    """The NaN-price path the guards exist for: no fabricated fill, no fabricated price."""
    n = 30
    st = E.new_state(1000.0, str(DATES[0].date()), V9)
    tr = st["sleeves"]["stocks"]["tranches"][0]
    tr["units"], tr["last_px"], tr["cash"] = {"AAA": 1.0}, {"AAA": 100.0}, 150.0
    stock = _stock_frame(n)
    stock["AAA"] = np.nan
    etf = _etf_frame(n)
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(["BBB", "CCC"], 0), stock, etf, 0.0, V9)
    sides = {o["ticker"]: o["side"] for o in orders if o["sleeve"] == "stocks"}
    assert sides.get("AAA") == "hold_no_price"
    fills = E.settle(st, str(DATES[1].date()), stock.iloc[1], etf.iloc[1], V9)
    noted = [f for f in fills if f["ticker"] == "AAA"]
    assert noted and noted[0]["status"] == "noted"
    assert st["sleeves"]["stocks"]["tranches"][0]["units"]["AAA"] == pytest.approx(1.0)


@pytest.mark.xfail(strict=True, reason=(
    "the n-sleeve _mix() checks only completeness and the sum, and NaN defeats the sum check "
    "(abs(nan - 1) > 1e-9 is False): mix={'stocks': nan, 'etf': 0.5} and mix={'stocks': -0.5, "
    "'etf': 1.5} are both ACCEPTED today — the first funds a tranche with nan cash, the second "
    "shorts a sleeve. The hardening side's validate_mix rejects both. This is an exposure guard: "
    "reported under approval_needed with the exact diff, not patched here."))
@pytest.mark.parametrize("mix", [
    {"stocks": float("nan"), "etf": 0.5},
    {"stocks": -0.5, "etf": 1.5},
])
def test_a_nan_or_negative_mix_weight_is_refused(mix):
    with pytest.raises(ValueError):
        E.new_state(8000.0, "2026-01-05", {**V9, "mix": mix})


@pytest.mark.xfail(strict=True, reason=(
    "new_state() casts capital with float() and asks nothing else: -1000 opens every tranche at "
    "-125 USD of cash and nan opens them at nan. state_check would later flag cash_negative on a "
    "book that should never have existed. Same class of guard as the mix; reported, not patched."))
@pytest.mark.parametrize("capital", [-1000.0, float("nan")])
def test_a_nan_or_negative_capital_is_refused(capital):
    with pytest.raises(ValueError):
        E.new_state(capital, "2026-01-05", V9)
