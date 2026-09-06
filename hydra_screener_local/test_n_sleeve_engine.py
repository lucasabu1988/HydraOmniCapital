"""TASK-386 — the engine iterates N sleeves from the registry; the bundle reset conserves the book.

Default cfg (two names, 50/50) is covered by test_engine_golden / test_portfolio_engine unchanged.
Here: a third sleeve (a second EtfTrend instance with cost 3 bp) and mix (0.5, 0.3, 0.2)."""
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import V9  # noqa: E402
from core import portfolio_engine as E  # noqa: E402
from core.state_check import check  # noqa: E402
from sleeves.registry import build  # noqa: E402

DATES = pd.bdate_range("2026-01-05", periods=40)
CFG3 = {**V9, "tranches": 4, "step_bars": 5,
        "sleeves": ["stocks", "etf", {"name": "etf_slow", "type": "etf", "cost_bp": 3.0}],
        "mix": {"stocks": 0.5, "etf": 0.3, "etf_slow": 0.2}}


def _prices(cols, rows):
    return pd.DataFrame(rows, index=DATES[: len(rows)], columns=cols)


def _ranking(names, n=None):
    n = len(names) if n is None else n
    return pd.DataFrame({"ticker": names, "rank": range(1, len(names) + 1), "sector": ["Other"] * len(names),
                         "reason": [""] * len(names), "recommended": [i < n for i in range(len(names))],
                         "recommended_count": n})


def test_registry_builds_named_instances_and_refuses_duplicates():
    reg = build(CFG3)
    assert list(reg) == ["stocks", "etf", "etf_slow"]
    assert reg["etf_slow"].name == "etf_slow" and reg["etf_slow"].cost_bp == 3.0 and reg["etf"].cost_bp == V9["etf_cost_bp"]
    assert reg["etf_slow"].mark_frame == "etf" and reg["stocks"].mark_frame == "stocks"
    with pytest.raises(ValueError, match="duplicate"):
        build({**CFG3, "sleeves": ["etf", "etf"]})
    with pytest.raises(KeyError, match="unknown sleeve"):
        build({**CFG3, "sleeves": ["mr"]})


def test_new_state_splits_capital_by_mix_and_keeps_schema_1():
    st = E.new_state(1000.0, str(DATES[0].date()), CFG3)
    assert st["schema_version"] == 1 and "mix" not in st                     # policy lives in cfg (TASK-365)
    cash = {s: sum(tr["cash"] for tr in b["tranches"]) for s, b in st["sleeves"].items()}
    assert cash == pytest.approx({"stocks": 500.0, "etf": 300.0, "etf_slow": 200.0})
    with pytest.raises(ValueError, match="sums to"):
        E.new_state(1000.0, "2026-01-05", {**CFG3, "mix": {"stocks": 0.5, "etf": 0.3, "etf_slow": 0.3}})
    with pytest.raises(ValueError, match="no weight"):
        E.new_state(1000.0, "2026-01-05", {**CFG3, "mix": {"stocks": 0.7, "etf": 0.3}})


def test_bundle_reset_legs_net_to_zero_and_settle_funds_them():
    """Design section 4 worked example: owns 70 / 40 / 10 on a bundle of 120 -> targets 60 / 36 / 24,
    transfers -10 / -4 / +14."""
    st = E.new_state(1000.0, str(DATES[0].date()), CFG3)
    for s, own in (("stocks", 70.0), ("etf", 40.0), ("etf_slow", 10.0)):
        st["sleeves"][s]["tranches"][0]["cash"] = own
    px = _prices(["A"], [[10.0]])
    epx = _prices(list(V9["etf_universe"]), [[100.0] * 10])
    st, orders = E.plan(st, str(DATES[0].date()), _ranking(["A"], n=0), px, epx, 0.0, CFG3)
    legs = {o["sleeve"]: (o["dollars"] if o["side"] == "transfer_in" else -o["dollars"])
            for o in orders if o["side"] in ("transfer_in", "transfer_out")}
    assert legs == pytest.approx({"stocks": -10.0, "etf": -4.0, "etf_slow": 14.0})
    assert abs(sum(legs.values())) < 1e-9
    parks = {o["sleeve"]: o["dollars"] for o in orders if o["side"] == "park"}
    assert parks == pytest.approx({"stocks": 60.0, "etf": 36.0, "etf_slow": 24.0})
    assert {o["cost_bp"] for o in orders if o["sleeve"] == "etf_slow"} == {3.0}
    book_before = sum(tr["cash"] for b in st["sleeves"].values() for tr in b["tranches"])
    E.settle(st, str(DATES[1].date()), px.iloc[0], epx.iloc[0], CFG3)
    book_after = sum(tr["cash"] for b in st["sleeves"].values() for tr in b["tranches"])
    assert book_after == pytest.approx(book_before)
    assert {s: st["sleeves"][s]["tranches"][0]["cash"] for s in ("stocks", "etf", "etf_slow")} == pytest.approx(
        {"stocks": 60.0, "etf": 36.0, "etf_slow": 24.0})
    assert sum(t["dollars"] for t in st["transfers"]) == pytest.approx(0.0)
    # (no replay check here: the 70/40/10 owns were hand-set without a ledger, so the replay would rightly
    #  flag them; the consistent cycle below carries the replay assertion)


def test_three_sleeves_trade_and_mark_against_their_own_frame():
    """The two ETF sleeves both mark on the ETF row; the stock sleeve on the stock row; each sleeve's
    fills carry its own cost_bp; the replay stays clean through a full plan/settle/plan cycle."""
    rng = np.random.default_rng(386)
    stock_rows = 100.0 * np.cumprod(1 + rng.normal(0, 0.01, size=(40, 3)), axis=0)
    etf_rows = 100.0 * np.cumprod(1 + rng.normal(0.0005, 0.005, size=(40, 10)), axis=0)
    px = _prices(["A", "B", "C"], stock_rows)
    epx = _prices(list(V9["etf_universe"]), etf_rows)
    tb = pd.Series(0.0, index=DATES)
    cfg = {**CFG3, "etf_lookback_bars": 20, "etf_vol_bars": 10}
    st = E.new_state(1000.0, str(DATES[25].date()), cfg)
    st, orders = E.plan(st, str(DATES[25].date()), _ranking(["A", "B", "C"]), px.iloc[:26], epx.iloc[:26], tb.iloc[:26], cfg)
    assert {o["sleeve"] for o in orders} >= {"stocks", "etf", "etf_slow"}
    fills = E.settle(st, str(DATES[26].date()), px.iloc[26], epx.iloc[26], cfg)
    assert all(f["cost"] == pytest.approx(f["dollars"] * 3.0 / 1e4) for f in fills
               if f["sleeve"] == "etf_slow" and f["status"] == "filled")
    summary = E.summary_table(st, px.iloc[26], epx.iloc[26], cfg)
    assert set(summary["sleeves"]) == {"stocks", "etf", "etf_slow"}
    assert summary["total"] == pytest.approx(sum(v["value"] for v in summary["sleeves"].values()))
    st, orders2 = E.plan(st, str(DATES[30].date()), _ranking(["B", "C", "A"]), px.iloc[:31], epx.iloc[:31], tb.iloc[:31], cfg)
    assert st["week_index"] == 1 and all(o["tranche"] == 1 for o in orders2)
    assert [f.level for f in check(json.loads(json.dumps(st)), cfg=cfg) if f.level == "ERROR"] == []
    assert len({r["sleeve"] for r in st["interest"]}) == 3


def test_default_cfg_is_the_two_sleeve_engine():
    reg = build(V9)
    assert list(reg) == ["stocks", "etf"]
    st = E.new_state(800.0, str(DATES[0].date()), V9)
    assert all(tr["cash"] == 100.0 for b in st["sleeves"].values() for tr in b["tranches"])
    assert E._mix(V9, ["stocks", "etf"]) == {"stocks": 0.5, "etf": 0.5}
