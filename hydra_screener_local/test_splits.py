"""TASK-363 — splits in the live book (H-003): scaling, idempotency, replay, wiring behind APPLY_SPLITS.

ASTRA-02 adds the order of events around a fill: a split effective on or before the execution date
must scale the position before the fill is booked, one effective after it must be applied after, and
the per-ticker watermark must make either pass replay-safe.
"""
import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import portfolio_v9 as V  # noqa: E402
from config import V9  # noqa: E402
from core import portfolio_engine as E  # noqa: E402
from core.dividends import apply_dividends, holdings_before  # noqa: E402
from core.splits import (  # noqa: E402
    SplitOrderError,
    apply_splits,
    split_mark,
    summarize_splits,
)
from core.state_check import check  # noqa: E402
from test_portfolio_v9_cli import FakeEngine, _market, _rank  # noqa: E402


def _book():
    """8 tranches of 1000; stocks[0] holds AAA 10 @ 20 (bought 09-08, cost 0.2) and BBB 4 @ 50 (cost 0.2)."""
    st = E.new_state(8000.0, "2026-09-04", V9)
    st["last_run_date"] = "2026-09-11"
    tr = st["sleeves"]["stocks"]["tranches"][0]
    tr["units"] = {"AAA": 10.0, "BBB": 4.0}
    tr["last_px"] = {"AAA": 22.0, "BBB": 55.0}
    tr["cash"] = 1000.0 - (200.0 + 0.2) - (200.0 + 0.2)
    st["ledger"] = [
        {"exec_date": "2026-09-08", "sleeve": "stocks", "tranche": 0, "ticker": "AAA", "side": "buy",
         "units": 10.0, "price": 20.0, "dollars": 200.0, "cost": 0.2, "status": "filled"},
        {"exec_date": "2026-09-08", "sleeve": "stocks", "tranche": 0, "ticker": "BBB", "side": "buy",
         "units": 4.0, "price": 50.0, "dollars": 200.0, "cost": 0.2, "status": "filled"},
    ]
    return st


def test_two_for_one_scales_units_and_last_price():
    st = _book()
    new = apply_splits(st, [{"ticker": "AAA", "date": "2026-09-15", "ratio": 2.0}], "2026-09-18")
    tr = st["sleeves"]["stocks"]["tranches"][0]
    assert tr["units"]["AAA"] == pytest.approx(20.0) and tr["last_px"]["AAA"] == pytest.approx(11.0)
    assert tr["units"]["BBB"] == 4.0 and tr["last_px"]["BBB"] == 55.0
    assert len(new) == 1 and new[0]["units_before"] == 10.0 and new[0]["units_after"] == 20.0
    assert st["splits"] == new and summarize_splits(st)["count"] == 1


def test_reverse_split_and_not_held_and_outside_window():
    st = _book()
    new = apply_splits(st, [
        {"ticker": "BBB", "date": "2026-09-16", "ratio": 0.1},          # 1:10 reverse
        {"ticker": "ZZZ", "date": "2026-09-16", "ratio": 2.0},          # not held -> nothing
        {"ticker": "AAA", "date": "2026-09-01", "ratio": 2.0},          # before last_run_date -> ignored
        {"ticker": "AAA", "date": "2026-09-25", "ratio": 3.0},          # after today -> ignored
    ], "2026-09-18")
    tr = st["sleeves"]["stocks"]["tranches"][0]
    assert [r["ticker"] for r in new] == ["BBB"]
    assert tr["units"]["BBB"] == pytest.approx(0.4) and tr["last_px"]["BBB"] == pytest.approx(550.0)
    assert tr["units"]["AAA"] == 10.0


def test_same_split_twice_is_idempotent():
    st = _book()
    table = [{"ticker": "AAA", "date": "2026-09-15", "ratio": 2.0}]
    apply_splits(st, table, "2026-09-18")
    again = apply_splits(st, table, "2026-09-18")
    assert again == [] and st["sleeves"]["stocks"]["tranches"][0]["units"]["AAA"] == pytest.approx(20.0)


def test_fill_after_the_split_is_not_scaled():
    """Split 09-15; a further AAA buy settled 09-16 (post-split units) must stay as booked."""
    st = _book()
    tr = st["sleeves"]["stocks"]["tranches"][0]
    tr["units"]["AAA"] = 10.0 + 6.0
    tr["cash"] -= 6.0 * 11.0
    st["ledger"].append({"exec_date": "2026-09-16", "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
                         "side": "buy", "units": 6.0, "price": 11.0, "dollars": 66.0, "cost": 0.0, "status": "filled"})
    apply_splits(st, [{"ticker": "AAA", "date": "2026-09-15", "ratio": 2.0}], "2026-09-18")
    assert tr["units"]["AAA"] == pytest.approx(20.0 + 6.0)          # only the 10 pre-split units doubled
    assert st["splits"][0]["units_before"] == 10.0


def test_replay_and_holdings_are_split_aware():
    st = _book()
    apply_splits(st, [{"ticker": "AAA", "date": "2026-09-15", "ratio": 2.0}], "2026-09-18")
    assert check(st) == []                                              # ledger replay reproduces 20 units
    held = holdings_before(st, "2026-09-16")
    assert held[("stocks", 0, "AAA")] == pytest.approx(20.0)
    assert holdings_before(st, "2026-09-15")[("stocks", 0, "AAA")] == pytest.approx(10.0)
    # a dividend after the split pays on post-split units
    st["last_run_date"] = "2026-09-18"
    credited = apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-09-22", "dps": 0.5}], "2026-09-25")
    assert credited[0]["units"] == pytest.approx(20.0) and credited[0]["dollars"] == pytest.approx(10.0)


def test_pending_estimates_are_rescaled_but_dollars_untouched():
    st = _book()
    st["pending"] = [{"planned": "2026-09-11", "sleeve": "stocks", "tranche": 1, "ticker": "AAA", "side": "buy",
                      "dollars": 300.0, "est_units": 15.0, "est_price": 20.0}]
    apply_splits(st, [{"ticker": "AAA", "date": "2026-09-15", "ratio": 2.0}], "2026-09-18")
    o = st["pending"][0]
    assert o["dollars"] == 300.0 and o["est_units"] == pytest.approx(30.0) and o["est_price"] == pytest.approx(10.0)


# --- ASTRA-02: order of events by economic date --------------------------------------------------


def _one_name(cash=800.0):
    """Astra's probe book: stocks[0] holds AAA 10 @ 20 (bought 09-08, no cost) + 800 cash = 1000."""
    st = E.new_state(8000.0, "2026-09-04", V9)
    st["last_run_date"] = "2026-09-11"
    tr = st["sleeves"]["stocks"]["tranches"][0]
    tr.update(units={"AAA": 10.0}, last_px={"AAA": 20.0}, cash=cash)
    st["ledger"] = [
        {"exec_date": "2026-09-08", "sleeve": "stocks", "tranche": 0, "ticker": "AAA", "side": "buy",
         "units": 10.0, "price": 20.0, "dollars": 200.0, "cost": 0.0, "status": "filled"},
    ]
    return st


def _settle_around_split(st, order, ratio, price, date="2026-09-14"):
    """The CLI's order of events for one settle: splits effective on or before the execution date,
    the fills, then the splits effective after it. `price` is the post-split (Yahoo) close."""
    st["pending"] = [dict(order)]
    table = [{"ticker": "AAA", "date": date, "ratio": ratio}]
    before = apply_splits(st, table, date, upto=date)
    fills = E.settle(st, date, pd.Series({"AAA": price}), pd.Series(dtype=float), V9)
    after = apply_splits(st, table, date, after=date)
    return fills, before, after


_SELL = dict(planned="2026-09-11", sleeve="stocks", tranche=0, ticker="AAA", side="sell",
             dollars=200.0, est_units=10.0, est_price=20.0, cost_bp=0.0)


def test_split_on_full_exit_leaves_no_position():
    """Astra's probe, assertion unchanged. 10 AAA @ 20, 2:1 effective on the exit date, close=True:
    the tranche must end flat with the whole 1000 USD, not 900 and a phantom 10 shares."""
    st = _one_name()
    fills, before, after = _settle_around_split(st, dict(_SELL, close=True), 2.0, 10.0)
    tr = st["sleeves"]["stocks"]["tranches"][0]
    assert tr["units"].get("AAA", 0) == 0, tr                       # Astra's assertion, verbatim
    assert tr["cash"] == pytest.approx(1000.0)                      # 800 + 20 units x 10
    assert fills[0]["units"] == pytest.approx(20.0) and fills[0]["dollars"] == pytest.approx(200.0)
    assert "AAA" not in tr["last_px"]
    assert [r["units_after"] for r in before] == [20.0] and after == []
    assert split_mark(st, "AAA") == "2026-09-14" and check(st) == []


def test_partial_sell_on_the_split_date_keeps_the_value():
    """A dollar sell of 100 on the split date: half of the 20 post-split units, value unchanged."""
    st = _one_name()
    _settle_around_split(st, dict(_SELL, dollars=100.0), 2.0, 10.0)
    tr = st["sleeves"]["stocks"]["tranches"][0]
    assert tr["units"]["AAA"] == pytest.approx(10.0) and tr["cash"] == pytest.approx(900.0)
    assert tr["cash"] + tr["units"]["AAA"] * 10.0 == pytest.approx(1000.0)
    assert tr["last_px"]["AAA"] == pytest.approx(10.0) and check(st) == []


def test_reverse_split_on_full_exit_leaves_no_position():
    """1:10 reverse on the exit date: 10 units at 20 become 1 at 200, still 1000 USD out."""
    st = _one_name()
    fills, _, _ = _settle_around_split(st, dict(_SELL, close=True), 0.1, 200.0)
    tr = st["sleeves"]["stocks"]["tranches"][0]
    assert tr["units"].get("AAA", 0) == 0
    assert fills[0]["units"] == pytest.approx(1.0) and tr["cash"] == pytest.approx(1000.0)
    assert st["splits"][0]["units_after"] == pytest.approx(1.0) and check(st) == []


def test_split_after_a_late_confirmed_fill_applies_once_and_only_once():
    """The plan of 09-11 only settles on the 09-18 run, at the 09-14 close; the split is effective
    09-15. Moving all splits to the front would miss that fill (and then double-count it on the
    replay); the second pass must scale it exactly once."""
    st = _one_name()
    st["pending"] = [dict(planned="2026-09-11", sleeve="stocks", tranche=0, ticker="CCC",
                          side="buy", dollars=200.0, est_units=10.0, est_price=20.0, cost_bp=0.0)]
    E.settle(st, "2026-09-14", pd.Series({"CCC": 20.0}), pd.Series(dtype=float), V9)
    table = [{"ticker": "CCC", "date": "2026-09-15", "ratio": 2.0}]
    assert apply_splits(st, table, "2026-09-18", upto="2026-09-14") == []    # not this pass
    new = apply_splits(st, table, "2026-09-18", after="2026-09-14")
    tr = st["sleeves"]["stocks"]["tranches"][0]
    assert [r["units_before"] for r in new] == [10.0]               # the late fill is in the base
    assert tr["units"]["CCC"] == pytest.approx(20.0) and tr["last_px"]["CCC"] == pytest.approx(10.0)
    # a provider that publishes the same event again on the next run changes nothing
    assert apply_splits(st, table, "2026-09-18", after="2026-09-14") == []
    assert apply_splits(st, table, "2026-09-18") == []
    assert tr["units"]["CCC"] == pytest.approx(20.0) and len(st["splits"]) == 1
    assert check(st) == []


def test_watermark_replay_leaves_pending_estimates_alone():
    """The (date, sleeve, tranche, ticker) key cannot protect a tranche that holds nothing, so a
    replayed event used to rescale the pending estimates again. The watermark drops the event."""
    st = _one_name()
    st["pending"] = [{"planned": "2026-09-11", "sleeve": "stocks", "tranche": 1, "ticker": "AAA",
                      "side": "buy", "dollars": 300.0, "est_units": 15.0, "est_price": 20.0}]
    table = [{"ticker": "AAA", "date": "2026-09-15", "ratio": 2.0},
             {"ticker": "AAA", "date": "2026-09-15", "ratio": 2.0}]      # provider repeat, one event
    first = apply_splits(st, table, "2026-09-18")
    again = apply_splits(st, table, "2026-09-18")
    o = st["pending"][0]
    assert len(first) == 1 and again == []
    assert o["est_units"] == pytest.approx(30.0) and o["est_price"] == pytest.approx(10.0)
    assert o["dollars"] == 300.0
    assert st["sleeves"]["stocks"]["tranches"][0]["units"]["AAA"] == pytest.approx(20.0)
    assert split_mark(st, "AAA") == "2026-09-15"


def test_watermark_recovers_an_event_the_provider_published_late():
    """The window's lower bound is the ticker's watermark, not last_run_date: a split the provider
    failed to report inside its own window is still applied on a later run instead of vanishing."""
    st = _one_name()
    apply_splits(st, [{"ticker": "AAA", "date": "2026-09-15", "ratio": 2.0}], "2026-09-18")
    st["last_run_date"] = "2026-09-25"                       # a run went by with an empty table
    new = apply_splits(st, [{"ticker": "AAA", "date": "2026-09-22", "ratio": 2.0}], "2026-09-29")
    assert [r["date"] for r in new] == ["2026-09-22"]
    assert st["sleeves"]["stocks"]["tranches"][0]["units"]["AAA"] == pytest.approx(40.0)
    assert split_mark(st, "AAA") == "2026-09-22" and check(st) == []
    # an unmarked ticker keeps the old bound: no retroactive scaling from nothing
    assert apply_splits(st, [{"ticker": "BBB", "date": "2026-09-22", "ratio": 2.0}], "2026-09-29") == []


def test_a_split_reaching_the_book_after_that_day_fills_is_refused():
    """Astra's original sequence — settle, then one pass over the whole window — cannot silently
    leave a phantom position any more: the units it would scale have already been traded."""
    st = _one_name()
    st["pending"] = [dict(_SELL, close=True)]
    E.settle(st, "2026-09-14", pd.Series({"AAA": 10.0}), pd.Series(dtype=float), V9)
    with pytest.raises(SplitOrderError) as e:
        apply_splits(st, [{"ticker": "AAA", "date": "2026-09-14", "ratio": 2.0}], "2026-09-14")
    assert "stocks[0]" in str(e.value) and "upto=" in str(e.value)
    tr = st["sleeves"]["stocks"]["tranches"][0]
    assert tr["units"].get("AAA", 0) == 0 and st.get("splits") in (None, [])


def test_an_old_fill_on_the_date_of_a_late_published_split_is_not_refused():
    """The mirror case: the fill at 09-14 was booked in an earlier cycle (last plan 09-18), so it
    is already post-split and only the pre-09-14 base is scaled. That must still work."""
    st = _one_name()
    st["pending"] = [dict(planned="2026-09-11", sleeve="stocks", tranche=0, ticker="AAA",
                          side="buy", dollars=100.0, est_units=10.0, est_price=10.0, cost_bp=0.0)]
    E.settle(st, "2026-09-14", pd.Series({"AAA": 10.0}), pd.Series(dtype=float), V9)
    st["last_run_date"] = "2026-09-18"                       # that cycle closed
    st["split_marks"] = {"AAA": "2026-09-08"}                # watermark before the event
    new = apply_splits(st, [{"ticker": "AAA", "date": "2026-09-14", "ratio": 2.0}], "2026-09-25")
    tr = st["sleeves"]["stocks"]["tranches"][0]
    assert [r["units_before"] for r in new] == [10.0]        # only the pre-09-14 units
    assert tr["units"]["AAA"] == pytest.approx(20.0 + 10.0)
    assert check(st) == []


class SettlingEngine(FakeEngine):
    """FakeEngine's state and plan, the real settle (the fake one books no units)."""

    def settle(self, state, exec_date, stock_row, etf_row, cfg):
        self.settles += 1
        return E.settle(state, exec_date, stock_row, etf_row, cfg)


def test_cli_exits_the_position_when_the_split_lands_on_the_execution_date(tmp_path, monkeypatch):
    """End to end through run(): pending `close` sell planned 09-04, executed at the 09-08 close,
    2:1 effective 09-08. The tranche must end with the cash and no units."""
    V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=FakeEngine(), silent=True)
    st = json.loads((tmp_path / "portfolio_v9.json").read_text(encoding="utf-8"))
    st["last_run_date"] = "2026-09-04"
    st["pending"] = [{"planned": "2026-09-04", "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
                      "side": "sell", "close": True, "dollars": 100.0, "est_units": 10.0,
                      "est_price": 10.0, "cost_bp": 0.0, "week": 0}]
    tr = st["sleeves"]["stocks"]["tranches"][0]
    tr["units"] = {"AAA": 10.0}
    tr["last_px"] = {"AAA": 10.0}
    tr["cash"] = 12400.0
    st["ledger"] = [{"exec_date": "2026-09-01", "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
                     "side": "buy", "units": 10.0, "price": 10.0, "dollars": 100.0, "cost": 0.0,
                     "status": "filled"}]
    (tmp_path / "portfolio_v9.json").write_text(json.dumps(st), encoding="utf-8")

    def later(_u=None):
        idx = pd.DatetimeIndex(["2026-09-04", "2026-09-08"])
        m = _market()
        m["prices"] = pd.DataFrame({"AAA": [10.0, 5.0]}, index=idx)     # 5.0 = post-split close
        m["volumes"] = m["prices"] * 1000
        m["spy"] = pd.Series([400.0, 401.0], index=idx)
        m["etf"] = pd.DataFrame({t: [100.0, 101.0] for t in V9["etf_universe"]}, index=idx)
        m["irx"] = pd.Series([5.25, 5.20], index=idx)
        return m

    monkeypatch.setattr(V, "APPLY_SPLITS", True)
    out = V.run(tmp_path, fetch_fn=later, rank_fn=_rank, engine=SettlingEngine(), silent=True,
                split_fn=lambda _t: [{"ticker": "AAA", "date": "2026-09-08", "ratio": 2.0}])
    tr = out["state"]["sleeves"]["stocks"]["tranches"][0]
    assert "AAA" not in tr["units"]
    assert tr["cash"] == pytest.approx(12500.0)                         # 12400 + 20 x 5
    assert out["state"]["splits"][0]["units_after"] == pytest.approx(20.0)
    assert out["state"]["split_marks"]["AAA"] == "2026-09-08"
    sold = [f for f in out["state"]["ledger"] if f.get("side") == "sell"]
    assert sold[-1]["units"] == pytest.approx(20.0) and sold[-1]["dollars"] == pytest.approx(100.0)


def test_cli_split_fetch_covers_the_pending_names(tmp_path, monkeypatch):
    """The table is now fetched before settle, so a name that is only in a pending order (not yet
    in `units`, not yet in the ledger) must still be asked for."""
    V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=FakeEngine(), silent=True)
    st = json.loads((tmp_path / "portfolio_v9.json").read_text(encoding="utf-8"))
    st["last_run_date"] = "2026-09-04"
    st["pending"] = [{"planned": "2026-09-04", "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
                      "side": "buy", "dollars": 100.0, "est_units": 10.0, "est_price": 10.0,
                      "cost_bp": 0.0, "week": 0}]
    (tmp_path / "portfolio_v9.json").write_text(json.dumps(st), encoding="utf-8")
    asked = []

    def later(_u=None):
        idx = pd.DatetimeIndex(["2026-09-04", "2026-09-08"])
        m = _market()
        m["prices"] = pd.DataFrame({"AAA": [10.0, 5.0]}, index=idx)
        m["volumes"] = m["prices"] * 1000
        m["spy"] = pd.Series([400.0, 401.0], index=idx)
        m["etf"] = pd.DataFrame({t: [100.0, 101.0] for t in V9["etf_universe"]}, index=idx)
        m["irx"] = pd.Series([5.25, 5.20], index=idx)
        return m

    def table(tickers):
        asked.append(list(tickers))
        return []

    monkeypatch.setattr(V, "APPLY_SPLITS", True)
    V.run(tmp_path, fetch_fn=later, rank_fn=_rank, engine=SettlingEngine(), silent=True, split_fn=table)
    assert len(asked) == 1 and "AAA" in asked[0]


def _second_run(tmp_path, monkeypatch, flag, split_fn):
    V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank, engine=FakeEngine(), silent=True)
    st = json.loads((tmp_path / "portfolio_v9.json").read_text(encoding="utf-8"))
    st["last_run_date"] = "2026-09-04"
    st["pending"] = []
    st["sleeves"]["stocks"]["tranches"][0]["units"] = {"AAA": 10.0}
    st["sleeves"]["stocks"]["tranches"][0]["cash"] = 12400.0
    st["ledger"] = [{"exec_date": "2026-09-01", "sleeve": "stocks", "tranche": 0, "ticker": "AAA", "side": "buy",
                     "units": 10.0, "price": 10.0, "dollars": 100.0, "cost": 0.0, "status": "filled"}]
    (tmp_path / "portfolio_v9.json").write_text(json.dumps(st), encoding="utf-8")

    def later(_u=None):
        idx = pd.DatetimeIndex(["2026-09-04", "2026-09-08"])
        m = _market()
        m["prices"] = pd.DataFrame({"AAA": [10.0, 5.0]}, index=idx)
        m["volumes"] = m["prices"] * 1000
        m["spy"] = pd.Series([400.0, 401.0], index=idx)
        m["etf"] = pd.DataFrame({t: [100.0, 101.0] for t in V9["etf_universe"]}, index=idx)
        m["irx"] = pd.Series([5.25, 5.20], index=idx)
        return m

    monkeypatch.setattr(V, "APPLY_SPLITS", flag)
    return V.run(tmp_path, fetch_fn=later, rank_fn=_rank, engine=FakeEngine(), silent=True, split_fn=split_fn)


def test_run_applies_splits_only_when_the_flag_is_on(tmp_path, monkeypatch):
    calls = []

    def table(tickers):
        calls.append(list(tickers))
        return [{"ticker": "AAA", "date": "2026-09-06", "ratio": 2.0}]

    out = _second_run(tmp_path, monkeypatch, False, table)
    assert calls == [] and out["state"]["sleeves"]["stocks"]["tranches"][0]["units"]["AAA"] == 10.0

    out = _second_run(tmp_path / "on", monkeypatch, True, table)
    assert calls and "AAA" in calls[0]
    assert out["state"]["sleeves"]["stocks"]["tranches"][0]["units"]["AAA"] == pytest.approx(20.0)
    assert out["state"]["splits"][0]["ratio"] == 2.0
    sheet = open(out["instructions_md"], encoding="utf-8").read()
    assert "## Splits" in sheet and "AAA x2" in sheet
