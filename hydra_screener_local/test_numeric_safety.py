"""Audit phase 2 — numeric safety, preflight and price provenance. No network.

Reproductions R-201..R-210 in docs/AUDIT_REPRODUCTIONS.md.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core.portfolio_engine as E  # noqa: E402
import preflight as PF  # noqa: E402
from config import MAX_BAR_AGE_SESSIONS, V9  # noqa: E402
from core.numbers import (  # noqa: E402
    InvalidNumber,
    as_finite,
    is_finite_money,
    is_finite_price,
    is_valid_units,
    is_valid_weight,
    require_finite_price,
    require_valid_units,
    weights_sum_to_one,
)
from core.state_check import check  # noqa: E402
from data.quality import (  # noqa: E402
    ABSENT,
    FILLED,
    OBSERVED,
    STALE,
    classify,
    executable_prices,
    invalid_prices,
    is_executable,
    last_observed_dates,
)

STOCKS = ("AAA", "BBB", "CCC")
N = 301                                     # 300 bars after the anchor -> a renewal bar


def _frames(stock_overrides=None, etf_overrides=None, n=N):
    idx = pd.bdate_range("2025-01-01", periods=n)
    stocks = pd.DataFrame({t: np.linspace(10.0, 20.0, n) for t in STOCKS}, index=idx)
    etf = pd.DataFrame({t: np.linspace(50.0, 60.0, n) for t in V9["etf_universe"]}, index=idx)
    for t, v in (stock_overrides or {}).items():
        stocks.loc[idx[-1], t] = v
    for t, v in (etf_overrides or {}).items():
        etf.loc[idx[-1], t] = v
    return stocks, etf, idx


def _ranking(tickers=STOCKS):
    tickers = list(tickers)
    return pd.DataFrame({
        "ticker": tickers,
        "rank": range(1, len(tickers) + 1),
        "sector": ["Tech"] * len(tickers),
        "recommended": [True] * len(tickers),
        "reason": [""] * len(tickers),
        "composite": np.linspace(1.0, 0.5, len(tickers)),
    })


def _plan(stock_overrides=None, etf_overrides=None):
    stocks, etf, idx = _frames(stock_overrides, etf_overrides)
    st = E.new_state(100000.0, str(idx[0].date()), V9)
    st, orders = E.plan(st, str(idx[-1].date()), _ranking(), stocks, etf, 0.04, V9)
    return st, orders


# ------------------------------------------------------------------ validators
def test_validators_reject_every_bad_shape():
    for bad in (None, float("nan"), float("inf"), -float("inf"), "abc", True, [1]):
        assert not is_finite_price(bad), bad
    for bad in (0.0, -1.0, -1e-30):
        assert not is_finite_price(bad), bad
    assert is_finite_price(1e-12)
    assert is_finite_price(123.45)

    for bad in (None, float("nan"), float("inf"), "x", True):
        assert not is_finite_money(bad), bad
    assert is_finite_money(-500.0), "cash can be negative"
    assert is_finite_money(0.0)

    for bad in (None, float("nan"), -1.0, float("inf")):
        assert not is_valid_units(bad), bad
    assert not is_valid_units(0.0)
    assert is_valid_units(0.0, allow_zero=True)
    assert is_valid_units(3.5)

    for bad in (-0.01, 1.01, float("nan"), None):
        assert not is_valid_weight(bad), bad
    assert is_valid_weight(0.0) and is_valid_weight(1.0) and is_valid_weight(0.5)


def test_require_raises_instead_of_repairing():
    with pytest.raises(InvalidNumber):
        require_finite_price(float("nan"))
    with pytest.raises(InvalidNumber):
        require_finite_price(0.0)
    with pytest.raises(InvalidNumber):
        require_valid_units(-1.0)
    assert require_finite_price(10.0) == 10.0


def test_as_finite_is_display_only_and_never_invents_a_price():
    assert as_finite(float("nan")) is None
    assert as_finite(float("nan"), 0.0) == 0.0
    assert as_finite("nope") is None
    assert as_finite(5) == 5.0


def test_weights_sum_to_one_with_a_documented_tolerance():
    assert weights_sum_to_one({"a": 0.5, "b": 0.5})
    assert weights_sum_to_one({"a": 1 / 3, "b": 1 / 3, "c": 1 / 3})
    assert not weights_sum_to_one({"a": 0.5, "b": 0.4})
    assert not weights_sum_to_one({"a": -0.5, "b": 1.5})
    assert not weights_sum_to_one({})


def test_nan_is_truthy_which_is_why_or_zero_is_banned():
    """The pattern the audit outlawed: `nan or 0.0` is nan, not 0.0."""
    assert (float("nan") or 0.0) != 0.0
    assert np.isnan(float("nan") or 0.0)


# ------------------------------------------------------------------ R-201 / R-202
def test_r201_a_zero_close_no_longer_crashes_the_plan():
    """R-201 — phase 2.3. Pre-fix `plan()` raised ZeroDivisionError on a close of
    exactly 0.0, taking the whole daily run down with an opaque message."""
    st, orders = _plan(stock_overrides={"AAA": 0.0})
    assert orders, "the rest of the book must still plan"
    assert not any(o["ticker"] == "AAA" and o["side"] == "buy" for o in orders)
    rejected = [e for e in st["data_errors"] if e["ticker"] == "AAA"]
    assert rejected, "the refusal must be structured, not a crash"
    assert rejected[0]["code"] == "price_not_executable"
    assert "not a valid price" in rejected[0]["reason"]


def test_r202_a_negative_close_no_longer_produces_a_buy_order():
    """R-202 — phase 2.3. Pre-fix a close of -12.50 produced a real buy order:
    $575.86 at est_units = -46.07 shares, est_price = -12.50, straight onto the
    sheet Lucas executes by hand."""
    st, orders = _plan(stock_overrides={"AAA": -12.5})
    assert not any(o["ticker"] == "AAA" and o["side"] == "buy" for o in orders)
    assert all(o.get("est_units") is None or float(o["est_units"]) >= 0 for o in orders)
    assert all(o.get("est_price") is None or float(o["est_price"]) > 0 for o in orders)
    assert [e for e in st["data_errors"] if e["ticker"] == "AAA" and e["intent"] == "buy"]


@pytest.mark.parametrize("bad", [0.0, -12.5, float("nan"), float("inf")])
def test_no_order_ever_carries_an_invalid_price_or_unit_count(bad):
    """Acceptance criterion 3, checked at the engine boundary."""
    st, orders = _plan(stock_overrides={"AAA": bad}, etf_overrides={V9["etf_universe"][0]: bad})
    assert E.validate_orders(orders) == []
    for o in orders:
        assert is_finite_money(o["dollars"]) and float(o["dollars"]) >= 0.0
        if o.get("est_price") is not None:
            assert is_finite_price(o["est_price"])
        if o.get("est_units") is not None:
            assert is_valid_units(o["est_units"], allow_zero=True)


def test_validate_orders_catches_what_it_is_there_to_catch():
    bad = [
        {"sleeve": "stocks", "tranche": 0, "side": "buy", "ticker": "A", "dollars": float("nan")},
        {"sleeve": "stocks", "tranche": 0, "side": "buy", "ticker": "B", "dollars": -5.0},
        {"sleeve": "stocks", "tranche": 0, "side": "buy", "ticker": "C", "dollars": 10.0, "est_price": 0.0},
        {"sleeve": "stocks", "tranche": 0, "side": "buy", "ticker": "D", "dollars": 10.0, "est_units": -1.0},
        {"sleeve": "stocks", "tranche": 0, "side": "buy", "ticker": "E", "dollars": 10.0,
         "est_units": float("inf"), "est_price": 2.0},
    ]
    problems = E.validate_orders(bad)
    assert len(problems) == 5
    good = [{"sleeve": "etf", "tranche": 1, "side": "buy", "ticker": "SPY",
             "dollars": 100.0, "est_units": 2.0, "est_price": 50.0}]
    assert E.validate_orders(good) == []


def test_plan_fails_closed_when_an_order_would_be_unexecutable(monkeypatch):
    """Rule 10: a poisoned order list stops the run; nothing becomes pending.

    The guard is driven by corrupting the target weights the sizing reads, which is
    the shape any future signal bug would take.
    """
    stocks, etf, idx = _frames()
    st = E.new_state(100000.0, str(idx[0].date()), V9)
    monkeypatch.setattr(E, "stock_targets",
                        lambda *a, **k: pd.Series({"AAA": float("inf")}))
    with pytest.raises(E.DataError) as exc:
        E.plan(st, str(idx[-1].date()), _ranking(), stocks, etf, 0.04, V9)
    assert "unexecutable" in str(exc.value)
    assert st["pending"] == [], "nothing may become pending after a refusal"


def test_plan_raises_dataerror_on_a_non_finite_tranche_value():
    stocks, etf, idx = _frames()
    st = E.new_state(100000.0, str(idx[0].date()), V9)
    st["sleeves"]["stocks"]["tranches"][0]["cash"] = float("nan")
    with pytest.raises(E.DataError):
        E.plan(st, str(idx[-1].date()), _ranking(), stocks, etf, 0.04, V9)


# ------------------------------------------------------------------ R-210
def test_r210_an_unpriced_held_name_does_not_cancel_the_renewal():
    """R-210 — phase 2.3/rule 11, the worst finding of this phase.

    `own_by_sleeve` was computed with `float(px.get(t, last_px) or 0.0)`. NaN is
    truthy, so a held name with no print and no carried mark made the tranche value
    NaN; every subsequent comparison against NaN is False, so the renewal emitted
    **no buys, no sells and no transfer** — silently. On the golden market this
    reduced five consecutive weekly renewals from 25 orders to 1.
    """
    stocks, etf, idx = _frames()
    st = E.new_state(100000.0, str(idx[0].date()), V9)
    tr = st["sleeves"]["stocks"]["tranches"][0]
    tr["units"] = {"GHOST": 100.0}          # held, no print, no last_px
    tr["last_px"] = {}
    st, orders = E.plan(st, str(idx[-1].date()), _ranking(), stocks, etf, 0.04, V9)

    buys = [o for o in orders if o["side"] == "buy"]
    assert buys, "the renewal must still deploy the tranche"
    assert any(o["side"] == "hold_no_price" and o["ticker"] == "GHOST" for o in orders), \
        "the unpriced name must be visible on the sheet"
    assert [e for e in st["data_errors"] if e["ticker"] == "GHOST" and e["intent"] == "mark"], \
        "and recorded as a structured data error"
    for o in orders:
        assert is_finite_money(o["dollars"])


# ------------------------------------------------------------------ R-203..R-205
def _clean_state():
    st = E.new_state(100000.0, "2026-01-02", V9)
    st["last_run_date"] = "2026-01-02"
    return st


def test_r203_infinite_cash_is_named_as_non_finite():
    """R-203 — phase 2.4. Pre-fix +inf was only reported as a replay mismatch."""
    st = _clean_state()
    st["sleeves"]["stocks"]["tranches"][0]["cash"] = float("inf")
    codes = [f.code for f in check(st)]
    assert "non_finite" in codes


def test_r204_nan_cash_is_named_as_non_finite_even_when_the_replay_agrees():
    """R-204 — phase 2.4. `_f` coerced NaN to 0.0 for the replay arithmetic, so a
    NaN cash whose replay also landed at zero passed the whole check clean."""
    st = _clean_state()
    for tr in st["sleeves"]["stocks"]["tranches"]:
        tr["cash"] = 0.0
    for tr in st["sleeves"]["etf"]["tranches"]:
        tr["cash"] = 0.0
    st["capital_reference"] = 0.0
    st["sleeves"]["stocks"]["tranches"][0]["cash"] = float("nan")
    codes = [f.code for f in check(st)]
    assert "non_finite" in codes, "a NaN cash must be an error on its own terms"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -3.0])
def test_state_check_names_invalid_units_and_marks(bad):
    st = _clean_state()
    st["sleeves"]["stocks"]["tranches"][0]["units"] = {"AAA": bad}
    st["sleeves"]["stocks"]["tranches"][0]["last_px"] = {"AAA": 10.0}
    assert "non_finite" in [f.code for f in check(st)]

    st = _clean_state()
    st["sleeves"]["stocks"]["tranches"][0]["units"] = {"AAA": 5.0}
    st["sleeves"]["stocks"]["tranches"][0]["last_px"] = {"AAA": bad}
    assert "non_finite" in [f.code for f in check(st)]


def test_state_check_names_an_unexecutable_pending_order():
    st = _clean_state()
    st["pending"] = [{"sleeve": "stocks", "tranche": 0, "side": "buy", "ticker": "AAA",
                      "dollars": 100.0, "est_units": -4.0, "est_price": -25.0,
                      "planned": "2026-01-02"}]
    codes = [f.code for f in check(st)]
    assert "order_price_invalid" in codes
    assert "order_units_invalid" in codes


@pytest.mark.parametrize("mix,expect", [
    ({"stocks": -0.5, "etf": 1.5}, "mix_invalid"),
    ({"stocks": 0.5, "etf": 0.4}, "mix_not_normalised"),
    ({"stocks": float("nan"), "etf": 0.5}, "mix_invalid"),
    ({"stocks": 1.0}, "mix_missing_sleeve"),
    ({"stocks": 0.5, "etf": 0.4, "crypto": 0.1}, "mix_unknown_sleeve"),
])
def test_r205_state_check_names_an_impossible_mix(mix, expect):
    """R-205 — phase 2.4/8.3. Pre-fix a negative mix produced only a cascade of
    replay_cash mismatches and never said the weights were impossible."""
    st = _clean_state()
    st["mix"] = mix
    assert expect in [f.code for f in check(st)]


def test_a_valid_mix_is_accepted():
    st = _clean_state()
    st["mix"] = {"stocks": 0.5, "etf": 0.5}
    assert not [f for f in check(st) if f.code.startswith("mix")]


# ------------------------------------------------------------------ provenance
def test_last_observed_is_recorded_before_the_forward_fill():
    idx = pd.bdate_range("2026-01-01", periods=6)
    raw = pd.DataFrame({"A": [10, 11, np.nan, np.nan, np.nan, np.nan],
                        "B": [1, 2, 3, 4, 5, 6.0]}, index=idx)
    seen = last_observed_dates(raw)
    assert seen["A"] == str(idx[1].date())
    assert seen["B"] == str(idx[-1].date())


def test_r209_a_filled_price_is_labelled_and_never_executable():
    """R-209 — phase 2.6/2.7: forward-fill may serve analysis, never execution."""
    idx = pd.bdate_range("2026-01-01", periods=6)
    raw = pd.DataFrame({"OBS": np.linspace(10, 15, 6),
                        "GAP": [5.0, 5.1, 5.2, np.nan, np.nan, np.nan],
                        "DEAD": [7.0] + [np.nan] * 5}, index=idx)
    seen = last_observed_dates(raw)
    filled = raw.ffill(limit=3)
    out = classify(filled, idx[-1], last_observed=seen, max_age_sessions=0)

    assert out["OBS"]["status"] == OBSERVED
    assert out["GAP"]["status"] == STALE, "3 sessions old, budget 0"
    assert out["DEAD"]["status"] == ABSENT, "ffill limit exhausted"
    assert executable_prices(out) == {"OBS": pytest.approx(15.0)}
    assert is_executable(OBSERVED)
    for s in (FILLED, STALE, ABSENT):
        assert not is_executable(s)


def test_a_price_inside_the_budget_is_filled_not_observed():
    idx = pd.bdate_range("2026-01-01", periods=6)
    raw = pd.DataFrame({"GAP": [5.0, 5.1, 5.2, 5.3, 5.4, np.nan]}, index=idx)
    seen = last_observed_dates(raw)
    out = classify(raw.ffill(limit=3), idx[-1], last_observed=seen, max_age_sessions=2)
    assert out["GAP"]["status"] == FILLED
    assert out["GAP"]["age_sessions"] == 1
    assert executable_prices(out) == {}, "filled is inside the budget but still not executable"


def test_classify_fails_closed_without_provenance():
    """Unknown provenance is never reported as observed."""
    idx = pd.bdate_range("2026-01-01", periods=3)
    frame = pd.DataFrame({"A": [1.0, 2.0, 3.0]}, index=idx)
    out = classify(frame, idx[-1], last_observed=None)
    assert out["A"]["status"] == FILLED
    assert executable_prices(out) == {}


def test_invalid_prices_finds_non_positive_closes():
    idx = pd.bdate_range("2026-01-01", periods=3)
    frame = pd.DataFrame({"OK": [1.0, 2.0, 3.0], "ZERO": [1.0, 1.0, 0.0],
                          "NEG": [1.0, 1.0, -4.0], "GONE": [1.0, 1.0, np.nan]}, index=idx)
    bad = invalid_prices(frame, idx[-1])
    assert set(bad) == {"ZERO", "NEG"}
    assert bad["NEG"] == pytest.approx(-4.0)


# ------------------------------------------------------------------ preflight
def _pf(stocks, etf, idx, *, asof=None, reports=None, state=None):
    irx = pd.Series(4.0, index=idx)
    return PF.evaluate(stocks, etf, irx, state=state,
                       asof=asof if asof is not None else str(idx[-1].date()),
                       last_session=str(idx[-1].date()), reports=reports)


def _status(res, check_name):
    for r in res["rows"]:
        if r["check"] == check_name:
            return r["status"]
    return None


def test_r206_a_negative_etf_close_is_a_hard_preflight_failure():
    """R-206 — phase 2.5/2.8. `pd.notna(-3.0)` is True, so a negative ETF close
    passed the "ETFs present" check and the whole preflight came back clean."""
    stocks, etf, idx = _frames(etf_overrides={V9["etf_universe"][0]: -3.0})
    res = _pf(stocks, etf, idx)
    assert _status(res, "prices are valid") == "HARD"
    assert res["hard"] is True
    assert V9["etf_universe"][0] in res["invalid_prices"]["etf"]


def test_a_zero_close_is_also_hard():
    stocks, etf, idx = _frames(etf_overrides={V9["etf_universe"][1]: 0.0})
    res = _pf(stocks, etf, idx)
    assert _status(res, "prices are valid") == "HARD"


def test_a_missing_close_is_reported_but_is_not_an_invalid_price():
    stocks, etf, idx = _frames(etf_overrides={V9["etf_universe"][1]: np.nan})
    res = _pf(stocks, etf, idx)
    assert _status(res, "prices are valid") == "OK", "absent is a different finding"
    assert _status(res, "ETFs present") == "HARD"


def test_r207_a_bar_after_asof_is_a_hard_preflight_failure():
    """R-207 — phase 2.5. Nothing compared the last bar to the as-of instant, so a
    frame whose last row was a month in the future came back clean."""
    stocks, etf, idx = _frames()
    asof = str((idx[-1] - pd.Timedelta(days=30)).date())
    res = _pf(stocks, etf, idx, asof=asof)
    assert _status(res, "bar not in the future") == "HARD"
    assert res["hard"] is True


def test_a_bar_on_asof_is_accepted():
    stocks, etf, idx = _frames()
    res = _pf(stocks, etf, idx, asof=str(idx[-1].date()))
    assert _status(res, "bar not in the future") == "OK"


def test_the_staleness_budget_is_explicit_and_enforced():
    """Phase 2.5: an age threshold that is written down, not implied."""
    stocks, etf, idx = _frames()
    irx = pd.Series(4.0, index=idx)
    older = stocks.iloc[:-1]
    res = PF.evaluate(older, etf.iloc[:-1], irx.iloc[:-1],
                      asof=str(idx[-1].date()), last_session=str(idx[-1].date()))
    assert _status(res, "bar age") == "HARD"
    assert res["thresholds"]["MAX_BAR_AGE_SESSIONS"] == int(MAX_BAR_AGE_SESSIONS)

    fresh = _pf(stocks, etf, idx)
    assert _status(fresh, "bar age") == "OK"


def test_r208_provenance_is_recorded():
    """R-208 — phase 2.5: source and capture timestamp in the result."""
    stocks, etf, idx = _frames()
    res = _pf(stocks, etf, idx)
    assert _status(res, "provenance") == "WARN", "no reports -> say so, do not invent one"

    reports = {
        "stocks": {"source": "yfinance", "fetched_at": "2026-09-06T20:00:00Z",
                   "last_observed": {t: str(idx[-1].date()) for t in STOCKS},
                   "ffill_limit_bars": 3, "requested": 3, "downloaded": 3},
        "etf": {"source": "yfinance", "fetched_at": "2026-09-06T20:00:01Z",
                "last_observed": {t: str(idx[-1].date()) for t in V9["etf_universe"]},
                "ffill_limit_bars": 3},
        "^IRX": {"source": "yfinance", "fetched_at": "2026-09-06T20:00:02Z"},
    }
    res = _pf(stocks, etf, idx, reports=reports)
    assert _status(res, "provenance") == "OK"
    assert res["provenance"]["stocks"]["source"] == "yfinance"
    assert res["provenance"]["stocks"]["fetched_at"] == "2026-09-06T20:00:00Z"


def test_a_carried_etf_close_is_a_hard_preflight_failure():
    """Phase 2.6 at the gate: the ETF sleeve trades a fixed list, so each of those
    closes must have been printed on the planning bar, not forward-filled."""
    stocks, etf, idx = _frames()
    reports = {
        "stocks": {"source": "yfinance", "fetched_at": "2026-09-06T20:00:00Z",
                   "last_observed": {t: str(idx[-1].date()) for t in STOCKS}},
        "etf": {"source": "yfinance", "fetched_at": "2026-09-06T20:00:01Z",
                "last_observed": {t: str(idx[-1].date()) for t in V9["etf_universe"]}},
        "^IRX": {"source": "yfinance", "fetched_at": "2026-09-06T20:00:02Z"},
    }
    ok = _pf(stocks, etf, idx, reports=reports)
    assert _status(ok, "ETF prices observed") == "OK"

    stale_name = V9["etf_universe"][2]
    reports["etf"]["last_observed"][stale_name] = str(idx[-4].date())
    bad = _pf(stocks, etf, idx, reports=reports)
    assert _status(bad, "ETF prices observed") == "HARD"
    assert bad["hard"] is True
    assert bad["price_quality"]["etf"][stale_name]["status"] == STALE


def test_a_clean_frame_with_reports_has_no_hard_failure():
    stocks, etf, idx = _frames()
    reports = {
        "stocks": {"source": "yfinance", "fetched_at": "2026-09-06T20:00:00Z",
                   "last_observed": {t: str(idx[-1].date()) for t in STOCKS}},
        "etf": {"source": "yfinance", "fetched_at": "2026-09-06T20:00:01Z",
                "last_observed": {t: str(idx[-1].date()) for t in V9["etf_universe"]}},
        "^IRX": {"source": "yfinance", "fetched_at": "2026-09-06T20:00:02Z"},
    }
    res = _pf(stocks, etf, idx, reports=reports)
    hard = [r for r in res["rows"] if r["status"] == "HARD"]
    assert hard == [], f"unexpected hard rows: {hard}"
